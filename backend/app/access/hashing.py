"""Password hashing. scrypt (standard library) by default, argon2id automatically when `argon2-cffi` is installed.

Stored format: `scrypt$<n>$<r>$<p>$<salt b64>$<hash b64>` or an argon2 `$argon2id$...` string. `needs_rehash` tells the caller a
stronger setting is available so the hash can be upgraded at the next successful login. Plaintext is never stored or logged."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

N, R, P, DKLEN = 2 ** 15, 8, 1, 32
MAXMEM = 128 * 1024 * 1024

try:  # optional, stronger
    from argon2 import PasswordHasher  # type: ignore
    from argon2.exceptions import InvalidHashError, VerificationError  # type: ignore
    _ARGON: PasswordHasher | None = PasswordHasher()
except Exception:  # pragma: no cover - argon2 not installed in most setups
    _ARGON = None


def _b(x: bytes) -> str:
    return base64.b64encode(x).decode()


def hash_password(password: str) -> str:
    if _ARGON is not None:
        return _ARGON.hash(password)
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, dklen=DKLEN, maxmem=MAXMEM)
    return f"scrypt${N}${R}${P}${_b(salt)}${_b(dk)}"


def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    try:
        if stored.startswith("$argon2"):
            if _ARGON is None:
                return False
            try:
                return bool(_ARGON.verify(stored, password))
            except (VerificationError, InvalidHashError):
                return False
        kind, n, r, p, salt, want = stored.split("$")
        if kind != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(base64.b64decode(want)),
                            maxmem=MAXMEM)
        return hmac.compare_digest(dk, base64.b64decode(want))
    except (ValueError, TypeError):
        return False


def needs_rehash(stored: str) -> bool:
    if _ARGON is not None:
        return not stored.startswith("$argon2")
    try:
        kind, n, r, p, *_ = stored.split("$")
        return kind != "scrypt" or int(n) < N or int(r) < R
    except ValueError:
        return True


def check_strength(password: str) -> str:
    """Return a problem description, or '' when the password is acceptable."""
    if len(password) < 10:
        return "Use at least 10 characters."
    if len(set(password)) < 5:
        return "That password repeats too much. Mix different characters."
    if password.lower() in {"password123", "1234567890", "qwertyuiop", "password1234", "adminadmin"}:
        return "That password is far too common."
    return ""
