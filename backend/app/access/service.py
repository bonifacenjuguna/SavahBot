"""The access service: password, TOTP, passkeys, recovery codes, sessions, login activity, audit log and lockdown.

The rule: once you have at least TWO sign-in methods set up (password counts, and is always set up), every sign-in must prove
ANY TWO of them. This is decided here on the server for every request, never by the dashboard. Until a second method exists,
password-only sign-in keeps working so you can set one up (the Security page says so, and scores you down for it).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Any

from ..db import register_schema
from ..security import OwnerAuth
from . import hashing, qr, totp, webauthn

logger = logging.getLogger("savahbot.access")

register_schema([
    "CREATE TABLE IF NOT EXISTS access_totp (id INTEGER PRIMARY KEY, secret TEXT NOT NULL, confirmed INTEGER NOT NULL DEFAULT 0, created {REAL} NOT NULL, last_counter INTEGER NOT NULL DEFAULT 0)",
    """CREATE TABLE IF NOT EXISTS access_passkeys (
        id {PK}, cred_id TEXT NOT NULL UNIQUE, public_key TEXT NOT NULL, sign_count INTEGER NOT NULL DEFAULT 0, name TEXT NOT NULL DEFAULT 'Passkey',
        created {REAL} NOT NULL, last_used {REAL}, aaguid TEXT NOT NULL DEFAULT '', backup_eligible INTEGER NOT NULL DEFAULT 0, backup_state INTEGER NOT NULL DEFAULT 0)""",
    "CREATE TABLE IF NOT EXISTS access_recovery (id {PK}, code_hash TEXT NOT NULL UNIQUE, created {REAL} NOT NULL, used_ts {REAL})",
    """CREATE TABLE IF NOT EXISTS access_sessions (
        id TEXT PRIMARY KEY, created {REAL} NOT NULL, last_seen {REAL} NOT NULL, expires {REAL} NOT NULL, ip TEXT NOT NULL DEFAULT '', ua TEXT NOT NULL DEFAULT '',
        label TEXT NOT NULL DEFAULT '', factors TEXT NOT NULL DEFAULT '', step_up_until {REAL} NOT NULL DEFAULT 0, revoked_ts {REAL}, revoked_reason TEXT NOT NULL DEFAULT '',
        limited INTEGER NOT NULL DEFAULT 0, device TEXT NOT NULL DEFAULT '')""",
    "CREATE INDEX IF NOT EXISTS idx_access_sessions_live ON access_sessions (revoked_ts, expires)",
    """CREATE TABLE IF NOT EXISTS access_tickets (
        id TEXT PRIMARY KEY, purpose TEXT NOT NULL, created {REAL} NOT NULL, expires {REAL} NOT NULL, ip TEXT NOT NULL DEFAULT '', ua TEXT NOT NULL DEFAULT '',
        factors TEXT NOT NULL DEFAULT '', challenge TEXT NOT NULL DEFAULT '', tries INTEGER NOT NULL DEFAULT 0, data TEXT NOT NULL DEFAULT '')""",
    "CREATE TABLE IF NOT EXISTS access_events (id {PK}, ts {REAL} NOT NULL, kind TEXT NOT NULL, ok INTEGER NOT NULL, method TEXT NOT NULL DEFAULT '', ip TEXT NOT NULL DEFAULT '', ua TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '')",
    "CREATE INDEX IF NOT EXISTS idx_access_events_ts ON access_events (ts)",
    "CREATE TABLE IF NOT EXISTS access_audit (id {PK}, ts {REAL} NOT NULL, action TEXT NOT NULL, session TEXT NOT NULL DEFAULT '', ip TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '')",
    "CREATE INDEX IF NOT EXISTS idx_access_audit_ts ON access_audit (ts)",
])

TICKET_TTL = 300
CLASSES = ("password", "totp", "passkey", "recovery")   # four ways to prove yourself; any two DIFFERENT ones sign you in
LOCKDOWN_KEY = "access_lockdown"


class AccessError(Exception):
    def __init__(self, message: str, status: int = 400, code: str | None = None) -> None:
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def describe_ua(ua: str) -> str:
    u = ua.lower()
    os_ = next((n for k, n in (("android", "Android"), ("iphone", "iPhone"), ("ipad", "iPad"), ("windows", "Windows"), ("mac os", "Mac"), ("linux", "Linux")) if k in u), "Unknown device")
    br = next((n for k, n in (("edg/", "Edge"), ("opr/", "Opera"), ("firefox", "Firefox"), ("chrome", "Chrome"), ("safari", "Safari")) if k in u), "browser")
    return f"{br} on {os_}"


class AccessService(OwnerAuth):
    def __init__(self, settings: Any, db: Any, shared: Any = None, cfg: Any = None, bus: Any = None) -> None:
        super().__init__(settings, db, shared)
        self.cfg, self.bus = cfg, bus
        self._hash = ""
        self.alert: Any = None          # async callable(text) set by the container; sends a Telegram line to the owner
        self.lockdown = False

    # ------------------------------------------------------------------ setup
    def _c(self, key: str) -> Any:
        return self.cfg.get(key) if self.cfg is not None else getattr(self.settings, key)

    async def init(self) -> None:
        secret = self.settings.jwt_secret or await self.db.kv_get("_jwt_secret")
        if not secret:
            secret = secrets.token_urlsafe(32)
            await self.db.kv_set("_jwt_secret", secret)
        self._secret = secret
        stored = await self.db.kv_get("_owner_password_hash")
        env_pw = self.settings.owner_password or ""
        env_fp = hashlib.sha256(env_pw.encode()).hexdigest() if env_pw else ""
        user_set = bool(await self.db.kv_get("_owner_password_user_set"))
        old_fp = await self.db.kv_get("_owner_password_env_fp") or ""
        if not stored or (env_fp and env_fp != old_fp and not user_set):
            # First start on 1.2.0 (migrating the old plaintext copy), a fresh install, or you changed OWNER_PASSWORD and never set one here
            plain = env_pw or await self.db.kv_get("_owner_password") or ""
            if not plain:
                plain = secrets.token_urlsafe(12)
                self.password_generated = True
                logger.warning("=" * 60 + "\nNo OWNER_PASSWORD set. Generated dashboard password (shown once): %s\n"
                               "Set OWNER_PASSWORD in your host's variables, or change it on the Security page.\n" + "=" * 60, plain)
            stored = hashing.hash_password(plain)
            await self.db.kv_set("_owner_password_hash", stored)
            await self.db.kv_set("_owner_password_env_fp", env_fp)
            if self.password_generated:
                await self.db.kv_set("_owner_password_generated", "1")
        else:
            self.password_generated = bool(await self.db.kv_get("_owner_password_generated"))
        await self.db.kv_set("_owner_password", "")               # the old plaintext copy is wiped
        self._hash = stored
        self.lockdown = bool(await self.db.kv_get(LOCKDOWN_KEY))

    def check_password(self, candidate: str) -> bool:
        ok = hashing.verify_password(candidate, self._hash)
        return ok

    async def _maybe_rehash(self, candidate: str) -> None:
        if hashing.needs_rehash(self._hash):
            self._hash = hashing.hash_password(candidate)
            await self.db.kv_set("_owner_password_hash", self._hash)

    # ------------------------------------------------------------------ WebAuthn config
    def rp_id(self) -> str:
        explicit = str(self._c("webauthn_rp_id") or "").strip()
        if explicit:
            return explicit
        from urllib.parse import urlparse
        return urlparse(str(self._c("frontend_url") or "")).hostname or "localhost"

    def origins(self) -> list[str]:
        explicit = [o.strip().rstrip("/") for o in str(self._c("webauthn_origins") or "").split(",") if o.strip()]
        if explicit:
            return explicit
        fe = str(self._c("frontend_url") or "").strip().rstrip("/")
        return [fe] if fe else ["http://localhost:5173", "http://localhost:8080"]

    # ------------------------------------------------------------------ what is set up
    async def enrolled(self) -> dict[str, Any]:
        t = await self.db.fetchone("SELECT confirmed FROM access_totp WHERE id = 1")
        pk = await self.db.fetchall("SELECT id, name, created, last_used, backup_eligible, backup_state FROM access_passkeys ORDER BY id")
        rc = await self.db.fetchone("SELECT COUNT(*) AS n FROM access_recovery WHERE used_ts IS NULL")
        return {"password": True, "totp": bool(t and t["confirmed"]), "passkeys": pk, "recovery_left": int(rc["n"])}

    async def methods(self) -> int:
        e = await self.enrolled()
        return 1 + int(e["totp"]) + int(bool(e["passkeys"]))

    async def enforced(self) -> bool:
        return await self.methods() >= 2

    # ------------------------------------------------------------------ logging
    async def event(self, kind: str, ok: bool, method: str = "", ip: str = "", ua: str = "", detail: str = "") -> None:
        await self.db.execute("INSERT INTO access_events (ts, kind, ok, method, ip, ua, detail) VALUES (?, ?, ?, ?, ?, ?, ?)",
                              (time.time(), kind, int(ok), method, ip[:64], ua[:300], detail[:300]))

    async def audit(self, action: str, session: dict[str, Any] | None = None, ip: str = "", detail: str = "") -> None:
        await self.db.execute("INSERT INTO access_audit (ts, action, session, ip, detail) VALUES (?, ?, ?, ?, ?)",
                              (time.time(), action, (session or {}).get("id", "")[:12], ip[:64] or (session or {}).get("ip", ""), detail[:300]))
        if self.bus is not None:
            self.bus.publish("security_audit", {"action": action, "detail": detail[:100]})

    async def _alert(self, text: str) -> None:
        if self.alert is not None:
            try:
                await self.alert(text)
            except Exception:
                logger.exception("Security alert could not be sent")

    # ------------------------------------------------------------------ tickets (a half-finished sign-in)
    async def _ticket(self, purpose: str, ip: str, ua: str, factors: list[str] | None = None, challenge: str = "", data: str = "") -> str:
        tid = secrets.token_urlsafe(24)
        now = time.time()
        await self.db.execute("INSERT INTO access_tickets (id, purpose, created, expires, ip, ua, factors, challenge, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                              (_h(tid), purpose, now, now + TICKET_TTL, ip[:64], ua[:300], ",".join(factors or []), challenge, data))
        await self.db.execute("DELETE FROM access_tickets WHERE expires < ?", (now - 3600,))
        return tid

    async def _get_ticket(self, tid: str, purpose: str, ip: str) -> dict[str, Any]:
        row = await self.db.fetchone("SELECT * FROM access_tickets WHERE id = ? AND purpose = ?", (_h(tid or ""), purpose))
        if not row or row["expires"] < time.time() or row["ip"] != ip[:64] or row["tries"] >= 6:
            raise AccessError("That sign-in took too long or was started somewhere else. Start again.", 401, "ticket_expired")
        row["factor_list"] = [f for f in row["factors"].split(",") if f]
        return row

    async def _bump(self, ticket: dict[str, Any]) -> None:
        await self.db.execute("UPDATE access_tickets SET tries = tries + 1 WHERE id = ?", (ticket["id"],))

    async def _progress(self, ticket: dict[str, Any], factor: str, ip: str, ua: str, method_name: str) -> dict[str, Any]:
        have = sorted(set(ticket["factor_list"]) | {factor})
        await self.event("factor", True, factor, ip, ua)
        if len(have) >= 2 or not await self.enforced():
            await self.db.execute("DELETE FROM access_tickets WHERE id = ?", (ticket["id"],))
            return await self._finish(have, ip, ua, setup_needed=not await self.enforced())
        await self.db.execute("UPDATE access_tickets SET factors = ?, tries = 0 WHERE id = ?", (",".join(have), ticket["id"]))
        return {"step": "more", "ticket": ticket["_plain"], "have": have, "need": 1, "methods": await self._remaining(have)}

    async def _remaining(self, have: list[str]) -> list[str]:
        e = await self.enrolled()
        out = []
        if "password" not in have:
            out.append("password")
        if e["totp"] and "totp" not in have:
            out.append("totp")
        if e["passkeys"] and "passkey" not in have:
            out.append("passkey")
        if e["recovery_left"] and "recovery" not in have:
            out.append("recovery")
        return out

    # ------------------------------------------------------------------ sign-in
    async def _guard(self, ip: str) -> None:
        wait = await self.throttle.retry_after(ip)
        if wait:
            raise AccessError(f"Too many attempts. Try again in {wait} seconds.", 429)

    async def _fail(self, ip: str, ua: str, method: str, detail: str = "") -> None:
        await self.throttle.fail(ip)
        await self.event("login_failed", False, method, ip, ua, detail)

    async def start(self, ip: str, ua: str, first: str, ticket_id: str = "") -> dict[str, Any]:
        """Open or continue a sign-in ticket. `ticket_id` is empty for the first factor."""
        if ticket_id:
            t = await self._get_ticket(ticket_id, "login", ip)
        else:
            tid = await self._ticket("login", ip, ua)
            t = await self._get_ticket(tid, "login", ip)
            ticket_id = tid
        t["_plain"] = ticket_id
        return t

    async def login_password(self, password: str, ip: str, ua: str, ticket_id: str = "") -> dict[str, Any]:
        await self._guard(ip)
        t = await self.start(ip, ua, "password", ticket_id)
        if not self.check_password(password):
            await self._bump(t)
            await self._fail(ip, ua, "password")
            raise AccessError("That password is not right.", 401)
        await self.throttle.success(ip)
        await self._maybe_rehash(password)
        return await self._progress(t, "password", ip, ua, "password")

    async def login_code(self, ticket_id: str, kind: str, code: str, ip: str, ua: str) -> dict[str, Any]:
        await self._guard(ip)
        t = await self.start(ip, ua, kind, ticket_id)
        if kind == "totp":
            row = await self.db.fetchone("SELECT * FROM access_totp WHERE id = 1 AND confirmed = 1")
            counter = totp.verify(totp.unseal(self._secret, row["secret"]), code, last_counter=row["last_counter"]) if row else None
            if counter is None:
                await self._bump(t)
                await self._fail(ip, ua, "totp")
                raise AccessError("That code is not right, or it was already used. Wait for a new one.", 401)
            await self.db.execute("UPDATE access_totp SET last_counter = ? WHERE id = 1", (counter,))
        else:
            h = totp.hash_recovery(code, self._secret)
            used = await self.db.execute("UPDATE access_recovery SET used_ts = ? WHERE code_hash = ? AND used_ts IS NULL", (time.time(), h))
            if not used:
                await self._bump(t)
                await self._fail(ip, ua, "recovery")
                raise AccessError("That recovery code is not right, or it was already used.", 401)
            left = (await self.enrolled())["recovery_left"]
            await self.audit("recovery_code_used", None, ip, f"{left} left")
            await self._alert(f"🔑 A recovery code was used to sign in to the dashboard. {left} left. If this was not you, turn on lockdown.")
        await self.throttle.success(ip)
        return await self._progress(t, kind, ip, ua, kind)

    async def passkey_options(self, ip: str, ua: str, ticket_id: str = "") -> dict[str, Any]:
        await self._guard(ip)
        keys = await self.db.fetchall("SELECT cred_id FROM access_passkeys")
        if not keys:
            raise AccessError("No passkey has been set up yet.", 404)
        t = await self.start(ip, ua, "passkey", ticket_id)
        challenge = webauthn.new_challenge()
        await self.db.execute("UPDATE access_tickets SET challenge = ? WHERE id = ?", (challenge, t["id"]))
        return {"ticket": t["_plain"], "publicKey": {"challenge": challenge, "rpId": self.rp_id(), "timeout": 60000, "userVerification": "preferred",
                                                      "allowCredentials": [{"type": "public-key", "id": k["cred_id"]} for k in keys]}}

    async def login_passkey(self, ticket_id: str, cred: dict[str, Any], ip: str, ua: str) -> dict[str, Any]:
        await self._guard(ip)
        t = await self.start(ip, ua, "passkey", ticket_id)
        row = await self.db.fetchone("SELECT * FROM access_passkeys WHERE cred_id = ?", (str(cred.get("id", "")),))
        try:
            if not row or not t["challenge"]:
                raise webauthn.WebAuthnError("That passkey is not registered here.")
            r = cred["response"]
            count, _ = webauthn.verify_assertion(webauthn.unb64u(r["clientDataJSON"]), webauthn.unb64u(r["authenticatorData"]), webauthn.unb64u(r["signature"]),
                                                 t["challenge"], self.origins(), self.rp_id(), base64.b64decode(row["public_key"]), int(row["sign_count"]),
                                                 bool(self._c("webauthn_require_uv")))
        except (webauthn.WebAuthnError, KeyError, TypeError) as exc:
            await self._bump(t)
            await self._fail(ip, ua, "passkey", str(exc))
            raise AccessError(str(exc) if isinstance(exc, webauthn.WebAuthnError) else "The passkey data was incomplete.", 401) from exc
        await self.db.execute("UPDATE access_passkeys SET sign_count = ?, last_used = ? WHERE id = ?", (count, time.time(), row["id"]))
        await self.db.execute("UPDATE access_tickets SET challenge = '' WHERE id = ?", (t["id"],))   # a challenge works once
        await self.throttle.success(ip)
        return await self._progress(t, "passkey", ip, ua, "passkey")

    # ------------------------------------------------------------------ sessions
    async def _finish(self, factors: list[str], ip: str, ua: str, setup_needed: bool = False) -> dict[str, Any]:
        token, ttl = await self.new_session(ip, ua, factors)
        out: dict[str, Any] = {"token": token, "expires_in": ttl, "factors": factors}
        if setup_needed:
            out["setup_needed"] = True
        if self.lockdown:
            out["lockdown"] = True
        return out

    async def new_session(self, ip: str, ua: str, factors: list[str]) -> tuple[str, int]:
        now, ttl = time.time(), int(float(self._c("jwt_expire_hours")) * 3600)
        token = "sbs_" + secrets.token_urlsafe(32)
        device = hashlib.sha256(ua.encode()).hexdigest()[:16]
        known = await self.db.fetchone("SELECT 1 AS x FROM access_sessions WHERE device = ? LIMIT 1", (device,))
        await self.db.execute(
            "INSERT INTO access_sessions (id, created, last_seen, expires, ip, ua, label, factors, device, limited, step_up_until) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_h(token), now, now, now + ttl, ip[:64], ua[:300], describe_ua(ua), ",".join(factors), device, int(self.lockdown), now + 120))
        await self.event("login", True, "+".join(factors), ip, ua)
        await self.db.kv_set("restore_token_hash", "")     # a normal sign-in ends the one-time restore window
        if not known:
            await self.audit("new_device_signed_in", None, ip, describe_ua(ua))
            await self._alert(f"🆕 New device signed in to the dashboard: {describe_ua(ua)} ({ip}). If this was not you, open Security and turn on lockdown.")
        await self._trim_sessions()
        return token, ttl

    async def _trim_sessions(self) -> None:
        keep = max(1, int(self._c("security_max_sessions")))
        rows = await self.db.fetchall("SELECT id FROM access_sessions WHERE revoked_ts IS NULL AND expires > ? ORDER BY last_seen DESC", (time.time(),))
        for r in rows[keep:]:
            await self.db.execute("UPDATE access_sessions SET revoked_ts = ?, revoked_reason = 'oldest session closed (limit reached)' WHERE id = ?", (time.time(), r["id"]))

    async def authenticate(self, header: str, allow_limited: bool = False) -> dict[str, Any] | None:
        if not header.lower().startswith("bearer "):
            return None
        token = header[7:].strip()
        if not token.startswith("sbs_"):
            return None
        row = await self.db.fetchone("SELECT * FROM access_sessions WHERE id = ?", (_h(token),))
        now = time.time()
        if not row or row["revoked_ts"] or row["expires"] < now:
            return None
        idle = float(self._c("session_idle_minutes")) * 60
        if idle and now - row["last_seen"] > idle:
            await self.db.execute("UPDATE access_sessions SET revoked_ts = ?, revoked_reason = 'idle too long' WHERE id = ?", (now, row["id"]))
            return None
        if self.lockdown and not row["limited"]:
            raise AccessError("Lockdown is on. Sign in again to manage it.", 401, "lockdown")
        if row["limited"] and not allow_limited:
            raise AccessError("Lockdown is on. Only the Security page is available.", 403, "lockdown")
        if now - row["last_seen"] > 60:
            await self.db.execute("UPDATE access_sessions SET last_seen = ? WHERE id = ?", (now, row["id"]))
            row["last_seen"] = now
        return row

    async def logout(self, session: dict[str, Any]) -> None:
        await self.db.execute("UPDATE access_sessions SET revoked_ts = ?, revoked_reason = 'signed out' WHERE id = ?", (time.time(), session["id"]))
        await self.event("logout", True, "", session["ip"], session["ua"])

    async def sessions(self, current: str) -> list[dict[str, Any]]:
        rows = await self.db.fetchall("SELECT id, created, last_seen, expires, ip, label, factors, limited FROM access_sessions WHERE revoked_ts IS NULL AND expires > ? ORDER BY last_seen DESC", (time.time(),))
        for r in rows:
            r["current"] = r["id"] == current
            r["factors"] = [f for f in r["factors"].split(",") if f]
            r["ref"] = r["id"][:16]          # what the dashboard sends back to revoke; the full id is never shown
            del r["id"]
        return rows

    async def revoke(self, ref: str, session: dict[str, Any], reason: str = "revoked by you") -> bool:
        row = await self.db.fetchone("SELECT id FROM access_sessions WHERE id LIKE ? AND revoked_ts IS NULL", (ref[:16] + "%",)) if len(ref) >= 16 else None
        if not row:
            return False
        await self.db.execute("UPDATE access_sessions SET revoked_ts = ?, revoked_reason = ? WHERE id = ?", (time.time(), reason, row["id"]))
        await self.audit("session_revoked", session, "", row["id"][:12])
        return True

    async def revoke_others(self, session: dict[str, Any], reason: str = "revoked by you") -> int:
        n = await self.db.execute("UPDATE access_sessions SET revoked_ts = ?, revoked_reason = ? WHERE revoked_ts IS NULL AND id != ?", (time.time(), reason, session["id"]))
        await self.audit("other_sessions_revoked", session, "", f"{n} closed")
        return n

    # ------------------------------------------------------------------ step-up
    STEP_UP_SECONDS = 300

    def fresh(self, session: dict[str, Any]) -> bool:
        return session["step_up_until"] > time.time()

    def require_fresh(self, session: dict[str, Any]) -> None:
        if not self.fresh(session):
            raise AccessError("Confirm it is you first.", 403, "step_up_required")

    async def step_up(self, session: dict[str, Any], kind: str, code: str, ip: str) -> int:
        await self._guard(ip)
        ok = False
        if kind == "password":
            ok = self.check_password(code)
        elif kind == "totp":
            row = await self.db.fetchone("SELECT * FROM access_totp WHERE id = 1 AND confirmed = 1")
            counter = totp.verify(totp.unseal(self._secret, row["secret"]), code, last_counter=row["last_counter"]) if row else None
            if counter is not None:
                ok = True
                await self.db.execute("UPDATE access_totp SET last_counter = ? WHERE id = 1", (counter,))
        elif kind == "recovery":
            ok = bool(await self.db.execute("UPDATE access_recovery SET used_ts = ? WHERE code_hash = ? AND used_ts IS NULL", (time.time(), totp.hash_recovery(code, self._secret))))
        if not ok:
            await self._fail(ip, session["ua"], f"step-up {kind}")
            raise AccessError("That did not check out.", 401)
        await self.throttle.success(ip)
        until = time.time() + int(float(self._c("security_step_up_minutes")) * 60)
        await self.db.execute("UPDATE access_sessions SET step_up_until = ? WHERE id = ?", (until, session["id"]))
        session["step_up_until"] = until
        return int(until - time.time())

    # ------------------------------------------------------------------ changing things
    async def change_password(self, session: dict[str, Any], current: str, new: str, ip: str) -> int:
        await self._guard(ip)
        if not self.check_password(current):
            await self._fail(ip, session["ua"], "change password")
            raise AccessError("Your current password is not right.", 401)
        problem = hashing.check_strength(new)
        if problem:
            raise AccessError(problem)
        if hmac.compare_digest(current, new):
            raise AccessError("Choose a password you have not used just now.")
        self._hash = hashing.hash_password(new)
        await self.db.kv_set("_owner_password_hash", self._hash)
        await self.db.kv_set("_owner_password_user_set", "1")
        closed = await self.revoke_others(session, "password changed")
        await self.audit("password_changed", session, ip, f"{closed} other sessions closed")
        await self._alert("🔐 The dashboard password was changed. Other devices were signed out.")
        return closed

    async def totp_begin(self, session: dict[str, Any], account: str, issuer: str) -> dict[str, Any]:
        self.require_fresh(session)
        if (await self.enrolled())["totp"]:
            raise AccessError("An authenticator app is already set up. Remove it first to replace it.")
        secret = totp.new_secret()
        await self.db.execute("DELETE FROM access_totp WHERE id = 1")
        await self.db.execute("INSERT INTO access_totp (id, secret, confirmed, created) VALUES (1, ?, 0, ?)", (totp.seal(self._secret, secret), time.time()))
        uri = totp.otpauth_uri(secret, account, issuer)
        return {"secret": secret, "uri": uri, "qr": qr.svg(uri)}

    async def totp_confirm(self, session: dict[str, Any], code: str) -> dict[str, Any]:
        self.require_fresh(session)
        row = await self.db.fetchone("SELECT * FROM access_totp WHERE id = 1 AND confirmed = 0")
        counter = totp.verify(totp.unseal(self._secret, row["secret"]), code) if row else None
        if counter is None:
            raise AccessError("That code is not right. Check your phone's clock and try the next code.", 400)
        await self.db.execute("UPDATE access_totp SET confirmed = 1, last_counter = ? WHERE id = 1", (counter,))
        await self.audit("totp_enabled", session)
        codes = await self.new_recovery() if not (await self.enrolled())["recovery_left"] else None
        return {"ok": True, "recovery_codes": codes}

    async def new_recovery(self) -> list[str]:
        codes = totp.new_recovery_codes()
        await self.db.execute("DELETE FROM access_recovery")
        for c in codes:
            await self.db.execute("INSERT INTO access_recovery (code_hash, created) VALUES (?, ?)", (totp.hash_recovery(c, self._secret), time.time()))
        return codes

    async def regenerate_recovery(self, session: dict[str, Any]) -> list[str]:
        self.require_fresh(session)
        codes = await self.new_recovery()
        await self.audit("recovery_codes_regenerated", session)
        return codes

    async def _can_remove(self, what: str) -> None:
        if await self.methods() <= 2:
            raise AccessError(f"You need at least two sign-in methods. Add another one before removing {what}.", 409)

    async def totp_remove(self, session: dict[str, Any]) -> None:
        self.require_fresh(session)
        if (await self.enrolled())["totp"]:
            await self._can_remove("the authenticator app")
        await self.db.execute("DELETE FROM access_totp WHERE id = 1")
        await self.audit("totp_removed", session)

    async def passkey_register_options(self, session: dict[str, Any], app_name: str) -> dict[str, Any]:
        self.require_fresh(session)
        challenge = webauthn.new_challenge()
        tid = await self._ticket("register", session["ip"], session["ua"], challenge=challenge)
        keys = await self.db.fetchall("SELECT cred_id FROM access_passkeys")
        return {"ticket": tid, "publicKey": {
            "challenge": challenge, "rp": {"id": self.rp_id(), "name": app_name}, "timeout": 60000, "attestation": "none",
            "user": {"id": webauthn.b64u(b"savahbot-owner"), "name": "owner", "displayName": f"{app_name} owner"},
            "pubKeyCredParams": [{"type": "public-key", "alg": -7}, {"type": "public-key", "alg": -8}, {"type": "public-key", "alg": -257}],
            "authenticatorSelection": {"residentKey": "preferred", "userVerification": "preferred"},
            "excludeCredentials": [{"type": "public-key", "id": k["cred_id"]} for k in keys]}}

    async def passkey_register(self, session: dict[str, Any], ticket_id: str, cred: dict[str, Any], name: str) -> dict[str, Any]:
        self.require_fresh(session)
        row = await self.db.fetchone("SELECT * FROM access_tickets WHERE id = ? AND purpose = 'register'", (_h(ticket_id or ""),))
        if not row or row["expires"] < time.time() or not row["challenge"]:
            raise AccessError("That took too long. Start again.", 400)
        await self.db.execute("DELETE FROM access_tickets WHERE id = ?", (row["id"],))
        try:
            r = cred["response"]
            reg = webauthn.verify_registration(webauthn.unb64u(r["clientDataJSON"]), webauthn.unb64u(r["attestationObject"]), row["challenge"], self.origins(),
                                               self.rp_id(), bool(self._c("webauthn_require_uv")))
        except (webauthn.WebAuthnError, KeyError, TypeError) as exc:
            raise AccessError(str(exc) if isinstance(exc, webauthn.WebAuthnError) else "The passkey data was incomplete.") from exc
        cid = webauthn.b64u(reg.credential_id)
        if await self.db.fetchone("SELECT 1 AS x FROM access_passkeys WHERE cred_id = ?", (cid,)):
            raise AccessError("That passkey is already registered.", 409)
        pid = await self.db.insert(
            "INSERT INTO access_passkeys (cred_id, public_key, sign_count, name, created, aaguid, backup_eligible, backup_state) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, base64.b64encode(reg.public_key).decode(), reg.sign_count, (name or "Passkey").strip()[:40] or "Passkey", time.time(), reg.aaguid, int(reg.backup_eligible), int(reg.backup_state)))
        await self.audit("passkey_added", session, "", name[:40])
        return {"id": pid, "recovery_codes": await self.new_recovery() if not (await self.enrolled())["recovery_left"] else None}

    async def passkey_remove(self, session: dict[str, Any], pid: int) -> bool:
        self.require_fresh(session)
        e = await self.enrolled()
        if len(e["passkeys"]) == 1:
            await self._can_remove("your last passkey")
        n = await self.db.execute("DELETE FROM access_passkeys WHERE id = ?", (pid,))
        if n:
            await self.audit("passkey_removed", session)
        return bool(n)

    async def passkey_rename(self, pid: int, name: str) -> bool:
        return bool(await self.db.execute("UPDATE access_passkeys SET name = ? WHERE id = ?", ((name or "Passkey").strip()[:40] or "Passkey", pid)))

    # ------------------------------------------------------------------ lockdown
    async def set_lockdown(self, on: bool, session: dict[str, Any] | None, source: str = "dashboard") -> None:
        self.lockdown = on
        await self.db.kv_set(LOCKDOWN_KEY, "1" if on else "")
        if on:
            now = time.time()   # every session becomes "limited": it can only reach the Security page until you sign in again
            await self.db.execute("UPDATE access_sessions SET revoked_ts = ?, revoked_reason = 'lockdown' WHERE revoked_ts IS NULL AND id != ?", (now, (session or {}).get("id", "")))
            if session:
                await self.db.execute("UPDATE access_sessions SET limited = 1 WHERE id = ?", (session["id"],))
        if not on:
            await self.db.execute("UPDATE access_sessions SET limited = 0 WHERE limited = 1")
        await self.audit("lockdown_on" if on else "lockdown_off", session, "", source)
        await self._alert("🚨 Lockdown is ON. All other sessions were closed." if on else "✅ Lockdown was lifted.")

    # ------------------------------------------------------------------ reading
    async def events(self, limit: int = 60, kind: str = "") -> list[dict[str, Any]]:
        where, params = ("WHERE kind = ?", [kind]) if kind else ("", [])
        rows = await self.db.fetchall(f"SELECT ts, kind, ok, method, ip, ua, detail FROM access_events {where} ORDER BY ts DESC, id DESC LIMIT ?", [*params, min(limit, 200)])
        for r in rows:
            r["device"] = describe_ua(r.pop("ua"))
        return rows

    async def audit_log(self, limit: int = 60) -> list[dict[str, Any]]:
        return await self.db.fetchall("SELECT ts, action, session, ip, detail FROM access_audit ORDER BY ts DESC, id DESC LIMIT ?", (min(limit, 200),))

    async def purge(self, now: float) -> None:
        cut = now - int(self._c("security_log_retention_days")) * 86400
        for t in ("access_events", "access_audit"):
            await self.db.execute(f"DELETE FROM {t} WHERE ts < ?", (cut,))
        await self.db.execute("DELETE FROM access_sessions WHERE (revoked_ts IS NOT NULL AND revoked_ts < ?) OR expires < ?", (now - 30 * 86400, now - 30 * 86400))

    async def readiness(self, session: dict[str, Any]) -> dict[str, Any]:
        e = await self.enrolled()
        fe = str(self._c("frontend_url") or "")
        recent_fail = await self.db.fetchone("SELECT COUNT(*) AS n FROM access_events WHERE kind = 'login_failed' AND ts > ?", (time.time() - 86400,))
        others = len(await self.sessions(session["id"])) - 1
        checks = [
            {"id": "password", "ok": True, "weight": 1, "title": "Password is stored as a salted hash", "fix": ""},
            {"id": "second", "ok": await self.methods() >= 2, "weight": 3, "title": "A second sign-in method is set up (required for two-step sign-in)",
             "fix": "Add an authenticator app or a passkey below. Until then anyone with your password can sign in."},
            {"id": "passkey", "ok": bool(e["passkeys"]), "weight": 2, "title": "A passkey is registered", "fix": "Passkeys cannot be phished. Add one on this device."},
            {"id": "totp", "ok": e["totp"], "weight": 1, "title": "An authenticator app is set up", "fix": "A backup that works on any phone."},
            {"id": "recovery", "ok": e["recovery_left"] >= 3, "weight": 2, "title": "At least 3 recovery codes are left", "fix": "Make new recovery codes and keep them somewhere safe."},
            {"id": "https", "ok": fe.startswith("https://"), "weight": 2, "title": "The dashboard address uses HTTPS", "fix": "Set FRONTEND_URL to your https:// dashboard address (passkeys need it too)."},
            {"id": "generated", "ok": not self.password_generated or bool(await self.db.kv_get("_owner_password_user_set")), "weight": 2,
             "title": "You chose your own password", "fix": "The first password was generated and printed in the logs. Change it."},
            {"id": "sessions", "ok": others <= 3, "weight": 1, "title": "No pile of old sessions", "fix": "Sign out devices you do not use."},
            {"id": "lockdown", "ok": not self.lockdown, "weight": 1, "title": "Lockdown is off", "fix": "Lift it when you are safe."},
        ]
        got, total = sum(c["weight"] for c in checks if c["ok"]), sum(c["weight"] for c in checks)
        return {"score": round(100 * got / total), "checks": checks, "failed_logins_24h": recent_fail["n"], "other_sessions": others}
