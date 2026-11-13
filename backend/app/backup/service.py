"""Backup service: make an encrypted backup, check one, restore one (with a safety snapshot and an undo)."""
from __future__ import annotations

import asyncio
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
        self._run: dict[str, Any] | None = None
        self._cancel = False

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

    # ------------------------------------------------------------------ progress (1.4.3)
    # One restore runs at a time. The screen polls progress_info() while the restore request is open, so a long restore shows real movement
    # (which part, how many rows) and, if the connection drops, the screen can still find out how it ended.
    def progress_info(self) -> dict[str, Any]:
        run = getattr(self, "_run", None)
        if not run:
            return {"state": "idle"}
        return {**run, "scopes": [dict(x) for x in run["scopes"]], "elapsed": round((run["finished"] or time.time()) - run["started"], 1)}

    def request_cancel(self) -> bool:
        run = getattr(self, "_run", None)
        if run and run["state"] == "running" and run.get("cancellable"):
            self._cancel = True
            run["stage"] = "Cancelling, putting everything back"
            return True
        return False

    def _running(self) -> bool:
        run = getattr(self, "_run", None)
        return bool(run and run["state"] == "running" and time.time() - run["started"] < 3600)

    def _begin(self, chosen: list[str], parts: dict[str, Any], mode: str) -> dict[str, Any]:
        self._cancel = False
        self._run = {"id": secrets.token_hex(4), "state": "running", "mode": mode, "stage": "Opening the backup", "pct": 2, "started": time.time(), "finished": None,
                     "cancellable": False, "error": "", "result": None,
                     "scopes": [{"id": s, "label": archive.SCOPES[s]["label"], "state": "wait", "done": 0, "total": sum(len(d["rows"]) for d in parts[s]["tables"].values())}
                                for s in chosen]}
        return self._run

    def _recalc(self) -> None:
        run = self._run
        total = sum(x["total"] for x in run["scopes"]) or 1
        done = sum(x["done"] for x in run["scopes"])
        run["pct"] = round(10 + 80 * min(1.0, done / total), 1)

    def _stage(self, text: str, pct: float | None = None) -> None:
        self._run["stage"] = text
        if pct is not None:
            self._run["pct"] = pct

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
        if self._running():
            raise BackupError("A restore is already running. Wait for it to finish, or cancel it.")
        run = self._begin(chosen, parts, mode)
        try:
            await self._do_import(run, parts, chosen, mode, report)
        except Exception as exc:
            run.update(state="failed", error=str(exc), stage="Failed", finished=time.time(), cancellable=False)
            raise
        return report

    async def _do_import(self, run: dict[str, Any], parts: dict[str, Any], chosen: list[str], mode: str, report: dict[str, Any]) -> None:
        tables = [t for s in chosen for t in archive.SCOPES[s]["tables"]]
        kv = [k for s in chosen for k in archive.SCOPES[s]["kv"]]
        if "credentials" in chosen:
            tables.append("settings")
        self._stage("Making a safety copy so you can undo", 6)
        try:
            snap = await archive.snapshot_tables(self.c, tables, kv)
            await self._keep_undo(snap)
        except Exception as exc:     # nothing has been changed yet
            logger.exception("Could not make the safety copy before restoring")
            raise BackupError(f"Nothing was changed: the safety copy could not be made. ({exc})") from exc
        run["cancellable"] = True
        try:
            results: dict[str, Any] = {}
            for sc in run["scopes"]:
                sc["state"] = "run"
                self._stage(f"{'Replacing' if mode == 'replace' else 'Adding'}: {sc['label']}")

                def tick(n: int, sc: dict[str, Any] = sc) -> None:
                    sc["done"] = min(sc["total"], sc["done"] + n)
                    self._recalc()
                results[sc["id"]] = await archive.apply_scope(self.c, sc["id"], parts[sc["id"]], mode, tick, lambda: self._cancel)
                sc["state"], sc["done"] = "done", sc["total"]
                self._recalc()
            run["cancellable"] = False
            if mode == "replace":                       # verify: after a replace, the table sizes must be exactly the backup's
                self._stage("Checking the result", 92)
                for s in chosen:
                    for t, d in parts[s]["tables"].items():
                        if t in ("settings_secret", "settings"):
                            continue
                        demo = await archive._has_demo(self.c.db, t) if await archive._exists(self.c.db, t) else False
                        want = len(d["rows"]) - (sum(1 for r in d["rows"] if int(r[d["columns"].index("demo")] or 0)) if demo and "demo" in d["columns"] else 0)
                        have = (await self.c.db.fetchone(f"SELECT COUNT(*) AS n FROM {t}{' WHERE demo = 0' if demo else ''}"))["n"] if await archive._exists(self.c.db, t) else want
                        if have != want:
                            raise BackupError(f"Checking the result failed for {t}: expected {want} rows, found {have}.")
            self._stage("Reloading the bot with the restored data", 96)
            await self._reload(chosen)
        except Exception as exc:
            run["cancellable"] = False
            cancelled = self._cancel and "cancelled" in str(exc).lower()
            logger.exception("Import failed; rolling back")
            self._stage("Putting everything back as it was", 97)
            try:
                await archive.restore_snapshot(self.c, snap)
            except Exception as back:     # say so plainly instead of a bare server error (the safety copy is still kept for Undo)
                logger.exception("Rolling back after a failed import also failed")
                raise BackupError(f"The import failed ({exc}) and putting things back also failed ({back}). Press Undo the last restore to try again; a safety copy was kept.") from exc
            await self._reload(chosen)
            if cancelled:
                raise BackupError("Restore cancelled. Everything was put back as it was.") from exc
            raise BackupError(f"The import failed and everything was put back as it was. ({exc})") from exc
        report["applied"] = results
        report["can_undo"] = True
        added = sum(r["added"] for r in results.values())
        run.update(state="done", stage="Finished", pct=100, finished=time.time(), cancellable=False,
                   result={"added": added, "skipped": sum(r["skipped"] for r in results.values()), "failed": sum(r["failed"] for r in results.values()),
                           "error": next((r["error"] for r in results.values() if r["error"]), ""), "fingerprint": report["fingerprint"], "mode": mode})
        try:      # the data is already restored: a problem writing the log or sending the alert must not make the restore look like it failed
            await self.c.access.audit("backup_imported", None, "", f"{mode}: {', '.join(chosen)}")
            await self.c.access._alert(f"♻️ A backup was restored ({mode}: {', '.join(chosen)}).")
            self.c.bus.publish("backup", {"title": "Backup restored", "text": f"{mode}: {', '.join(chosen)}"})
        except Exception:
            logger.exception("Restored, but the log entry or alert could not be written")

    async def _keep_undo(self, snap: dict[str, Any]) -> None:
        def pack() -> str:     # a big snapshot takes a while to compress: do it off the event loop so the bot and the progress screen keep answering
            return base64.b64encode(zlib.compress(json.dumps(snap, default=str).encode(), 6)).decode()
        blob = await asyncio.to_thread(pack)
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
