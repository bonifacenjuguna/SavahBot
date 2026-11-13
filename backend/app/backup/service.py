"""Backup service: make an encrypted backup, check one, restore one (with a safety snapshot and an undo)."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import secrets
import time
import zlib
from typing import Any

from .. import __version__
from . import archive, container
from .container import BackupError

logger = logging.getLogger("savahbot.backup")
MAX_UPLOAD = 120 * 1024 * 1024
UNDO_KEY = "backup_undo"
TOKEN_KEY = "restore_token_hash"


class BackupService:
    def __init__(self, c: Any) -> None:
        self.c = c

    # ------------------------------------------------------------------ info
    async def info(self) -> dict[str, Any]:
        out = []
        for name, spec in archive.SCOPES.items():
            n = 0
            for t in spec["tables"]:
                if await archive._exists(self.c.db, t):
                    where = " WHERE demo = 0" if await archive._has_demo(self.c.db, t) else ""
                    n += (await self.c.db.fetchone(f"SELECT COUNT(*) AS n FROM {t}{where}"))["n"]
            out.append({"id": name, "label": spec["label"], "default": spec["default"], "rows": n})
        undo = await self.c.db.kv_get(UNDO_KEY)
        last = await self.c.db.kv_get("backup_last_export")
        return {"scopes": out, "undo_available": bool(undo), "last_export": float(last) if last else None, "version": __version__}

    # ------------------------------------------------------------------ export
    async def export(self, scopes: list[str], passphrase: str = "") -> dict[str, Any]:
        scopes = [s for s in dict.fromkeys(scopes) if s in archive.SCOPES]
        if not scopes:
            raise BackupError("Tick at least one thing to include.")
        parts = {s: await archive.dump_scope(self.c, s) for s in scopes}
        key = container.new_key()
        blob, fp = container.seal(archive.build_zip(parts, __version__), key, passphrase.strip(), {"scopes": scopes, "app": __version__})
        await self.c.db.kv_set("backup_last_export", str(time.time()))
        self.c.bus.publish("backup", {"title": "Backup exported", "text": f"{len(scopes)} area(s) saved to an encrypted file."})
        stamp = time.strftime("%Y-%m-%d-%H%M", time.gmtime())
        return {"filename": f"savahbot-{stamp}.svbak", "key": container.format_key(key), "fingerprint": fp, "size": len(blob), "scopes": scopes,
                "passphrase": bool(passphrase.strip()), "data": base64.b64encode(blob).decode()}

    # ------------------------------------------------------------------ open / verify
    def _decode(self, data_b64: str) -> bytes:
        try:
            blob = base64.b64decode(data_b64, validate=False)
        except (binascii.Error, ValueError) as exc:
            raise BackupError("The file could not be read.") from exc
        if len(blob) > MAX_UPLOAD:
            raise BackupError("That file is larger than the upload limit.")
        return blob

    def _open(self, data_b64: str, key: str, passphrase: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        plain, header = container.open_(self._decode(data_b64), container.parse_key(key), passphrase.strip())
        manifest, parts = archive.read_zip(plain)
        return header, manifest, parts

    def _summary(self, header: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
        return {"fingerprint": header["fp"], "created": manifest["created"], "app_version": manifest.get("app_version", ""), "passphrase": bool(header.get("pass")),
                "scopes": [{"id": s, "label": archive.SCOPES[s]["label"], "rows": sum(v["tables"].values()) if isinstance(v, dict) and "tables" in v else 0,
                            "tables": v["tables"]} for s, v in manifest["scopes"].items()]}

    async def verify(self, data_b64: str, key: str, passphrase: str = "") -> dict[str, Any]:
        header, manifest, _ = self._open(data_b64, key, passphrase)
        return {"ok": True, **self._summary(header, manifest)}

    # ------------------------------------------------------------------ import
    async def import_(self, data_b64: str, key: str, passphrase: str, mode: str, scopes: list[str], dry_run: bool) -> dict[str, Any]:
        if mode not in ("replace", "merge"):
            raise BackupError("Choose replace or merge.")
        header, manifest, parts = self._open(data_b64, key, passphrase)
        chosen = [s for s in (scopes or list(parts)) if s in parts]
        if not chosen:
            raise BackupError("Nothing in the backup matches what you picked.")
        def real(d: dict[str, Any]) -> int:     # Demo-mode sample rows in an older backup are never imported, so they are not part of the plan
            di = d["columns"].index("demo") if "demo" in d["columns"] else -1
            return sum(1 for r in d["rows"] if di < 0 or not int(r[di] or 0))
        plan = {s: {t: real(d) for t, d in parts[s]["tables"].items()} for s in chosen}
        report: dict[str, Any] = {"ok": True, "dry_run": dry_run, "mode": mode, "scopes": chosen, "plan": plan, **self._summary(header, manifest)}
        if dry_run:
            return report
        tables = [t for s in chosen for t in archive.SCOPES[s]["tables"]]
        kv = [k for s in chosen for k in archive.SCOPES[s]["kv"]]
        if "credentials" in chosen:
            tables.append("settings")
        try:
            snap = await archive.snapshot_tables(self.c, tables, kv)
            await self._keep_undo(snap)
        except Exception as exc:     # nothing has been changed yet
            logger.exception("Could not make the safety copy before restoring")
            raise BackupError(f"Nothing was changed: the safety copy could not be made. ({exc})") from exc
        try:
            results = {s: await archive.apply_scope(self.c, s, parts[s], mode) for s in chosen}
            if mode == "replace":                       # verify: after a replace, the table sizes must be exactly the backup's
                for s in chosen:
                    for t, d in parts[s]["tables"].items():
                        if t == "settings_secret":
                            continue
                        if t == "settings":
                            continue
                        demo = await archive._has_demo(self.c.db, t) if await archive._exists(self.c.db, t) else False
                        want = len(d["rows"]) - (sum(1 for r in d["rows"] if int(r[d["columns"].index("demo")] or 0)) if demo and "demo" in d["columns"] else 0)
                        have = (await self.c.db.fetchone(f"SELECT COUNT(*) AS n FROM {t}{' WHERE demo = 0' if demo else ''}"))["n"] if await archive._exists(self.c.db, t) else want
                        if have != want:
                            raise BackupError(f"Checking the result failed for {t}: expected {want} rows, found {have}.")
            await self._reload(chosen)
        except Exception as exc:
            logger.exception("Import failed; rolling back")
            try:
                await archive.restore_snapshot(self.c, snap)
            except Exception as back:     # 1.4.3: say so plainly instead of a bare server error (the safety copy is still kept for Undo)
                logger.exception("Rolling back after a failed import also failed")
                raise BackupError(f"The import failed ({exc}) and putting things back also failed ({back}). Press Undo the last restore to try again; a safety copy was kept.") from exc
            await self._reload(chosen)
            raise BackupError(f"The import failed and everything was put back as it was. ({exc})") from exc
        report["applied"] = results
        report["can_undo"] = True
        try:      # the data is already restored: a problem writing the log or sending the alert must not make the restore look like it failed
            await self.c.access.audit("backup_imported", None, "", f"{mode}: {', '.join(chosen)}")
            await self.c.access._alert(f"♻️ A backup was restored ({mode}: {', '.join(chosen)}).")
            self.c.bus.publish("backup", {"title": "Backup restored", "text": f"{mode}: {', '.join(chosen)}"})
        except Exception:
            logger.exception("Restored, but the log entry or alert could not be written")
        return report

    async def _keep_undo(self, snap: dict[str, Any]) -> None:
        blob = base64.b64encode(zlib.compress(json.dumps(snap, default=str).encode(), 6)).decode()
        await self.c.db.kv_set(UNDO_KEY, blob if len(blob) < 60 * 1024 * 1024 else "")

    async def undo(self) -> dict[str, Any]:
        raw = await self.c.db.kv_get(UNDO_KEY)
        if not raw:
            raise BackupError("There is nothing to undo.")
        snap = json.loads(zlib.decompress(base64.b64decode(raw)))
        await archive.restore_snapshot(self.c, snap)
        await self.c.db.kv_set(UNDO_KEY, "")
        await self._reload(["settings", "commands", "community", "knowledge", "moderation", "history", "credentials"])
        await self.c.access.audit("backup_import_undone")
        return {"ok": True, "tables": len(snap["tables"])}

    async def _reload(self, scopes: list[str]) -> None:
        c = self.c
        try:
            await c.cfg.load()
            await c.store.load_regulars()
            await c.hub.reload_blacklist()
            await c.knowledge.load()
            await c.learning.load()
            await c.rollups.load()
            if "credentials" in scopes:
                await c.access.init()
        except Exception:
            logger.exception("Could not refresh after restoring; restart the bot to be sure")

    # ------------------------------------------------------------------ first-run restore on a fresh deployment
    async def fresh(self) -> bool:
        a = await self.c.db.fetchone("SELECT COUNT(*) AS n FROM access_sessions")
        return a["n"] == 0 and not await self.c.db.kv_get("_owner_password_user_set")

    async def ensure_restore_token(self) -> None:
        if await self.fresh() and not await self.c.db.kv_get(TOKEN_KEY):
            token = secrets.token_urlsafe(18)
            await self.c.db.kv_set(TOKEN_KEY, hashlib.sha256(token.encode()).hexdigest())
            logger.warning("=" * 60 + "\nFresh install. To restore a backup BEFORE signing in, use this one-time token (shown once): %s\n"
                           "Signing in normally disables it.\n" + "=" * 60, token)

    async def check_token(self, token: str, ip: str) -> None:
        wait = await self.c.access.throttle.retry_after("restore:" + ip)
        if wait:
            raise BackupError(f"Too many attempts. Try again in {wait} seconds.")
        stored = await self.c.db.kv_get(TOKEN_KEY)
        ok = bool(stored) and await self.fresh() and secrets.compare_digest(hashlib.sha256((token or "").encode()).hexdigest(), stored)
        if not ok:
            await self.c.access.throttle.fail("restore:" + ip)
            raise BackupError("That restore token is not right, or it is no longer valid.")

    async def burn_token(self) -> None:
        await self.c.db.kv_set(TOKEN_KEY, "")
