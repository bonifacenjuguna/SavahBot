"""Owner-only authentication (standard library only).

SavahBot has exactly one user: you. Login exchanges the owner password for a signed token.
Tokens are HMAC-SHA256 signed, expire, and are checked in constant time.
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

logger = logging.getLogger("savahbot.security")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_token(secret: str, payload: dict[str, Any]) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_token(secret: str, token: str, now: float | None = None) -> dict[str, Any] | None:
    try:
        body, sig = token.split(".", 1)
        expected = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_unb64(body))
        if float(payload.get("exp", 0)) < (now if now is not None else time.time()):
            return None
        return payload
    except Exception:  # malformed token of any kind
        return None


class LoginThrottle:
    """Lock a client out after repeated failed logins."""

    def __init__(self, max_attempts: int = 5, lockout_seconds: int = 900) -> None:
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_seconds
        self._state: dict[str, tuple[int, float]] = {}  # key -> (failures, locked_until)

    def retry_after(self, key: str, now: float | None = None) -> int:
        now = now if now is not None else time.time()
        failures, locked_until = self._state.get(key, (0, 0.0))
        return int(locked_until - now) + 1 if locked_until > now else 0

    def fail(self, key: str, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        failures, locked_until = self._state.get(key, (0, 0.0))
        if locked_until and locked_until <= now:
            failures = 0
        failures += 1
        if failures >= self.max_attempts:
            self._state[key] = (0, now + self.lockout_seconds)
        else:
            self._state[key] = (failures, 0.0)

    def success(self, key: str) -> None:
        self._state.pop(key, None)


class OwnerAuth:
    def __init__(self, settings: Any, db: Any) -> None:
        self.settings = settings
        self.db = db
        self._password = ""
        self._secret = ""
        self.password_generated = False
        self.throttle = LoginThrottle(settings.login_max_attempts, settings.login_lockout_minutes * 60)

    async def init(self) -> None:
        password = self.settings.owner_password or await self.db.kv_get("_owner_password")
        if not password:
            password = secrets.token_urlsafe(12)
            await self.db.kv_set("_owner_password", password)
            self.password_generated = True
            logger.warning(
                "=" * 60 + "\nNo OWNER_PASSWORD set. Generated dashboard password (shown once): %s\n"
                "Set OWNER_PASSWORD in Railway variables to choose your own.\n" + "=" * 60,
                password,
            )
        self._password = password
        secret = self.settings.jwt_secret or await self.db.kv_get("_jwt_secret")
        if not secret:
            secret = secrets.token_urlsafe(32)
            await self.db.kv_set("_jwt_secret", secret)
        self._secret = secret

    def check_password(self, candidate: str) -> bool:
        return bool(self._password) and hmac.compare_digest(candidate.encode(), self._password.encode())

    def issue_token(self) -> tuple[str, int]:
        ttl = int(self.settings.jwt_expire_hours * 3600)
        exp = int(time.time()) + ttl
        return sign_token(self._secret, {"sub": "owner", "exp": exp}), ttl

    def verify(self, token: str) -> bool:
        payload = verify_token(self._secret, token)
        return bool(payload and payload.get("sub") == "owner")
