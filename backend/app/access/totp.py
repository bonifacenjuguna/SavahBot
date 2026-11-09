"""TOTP (RFC 6238, SHA-1, 6 digits, 30 s) and recovery codes, standard library only.

TOTP secrets are encrypted at rest (AES-GCM, key derived from the server secret) and never returned by the API after setup."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

STEP, DIGITS = 30, 6


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    return base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)


def code_at(secret: str, t: float, step: int = STEP) -> str:
    counter = int(t // step)
    mac = hmac.new(_key(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    num = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % 10 ** DIGITS
    return f"{num:0{DIGITS}d}"


def verify(secret: str, code: str, now: float | None = None, window: int = 1, last_counter: int = 0) -> int | None:
    """Return the matched time counter, or None. `last_counter` blocks replaying a code that was already used."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != DIGITS:
        return None
    now = now if now is not None else time.time()
    base = int(now // STEP)
    hit = None
    for delta in range(-window, window + 1):  # check every slot, so timing does not reveal which one matched
        c = base + delta
        if hmac.compare_digest(code_at(secret, c * STEP), code) and c > last_counter:
            hit = c if hit is None else hit
    return hit


def otpauth_uri(secret: str, account: str, issuer: str) -> str:
    return f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}"


def seal(server_secret: str, plaintext: str) -> str:
    key = hashlib.sha256(b"savahbot-totp|" + server_secret.encode()).digest()
    nonce = secrets.token_bytes(12)
    return base64.b64encode(nonce + AESGCM(key).encrypt(nonce, plaintext.encode(), b"totp")).decode()


def unseal(server_secret: str, blob: str) -> str:
    key = hashlib.sha256(b"savahbot-totp|" + server_secret.encode()).digest()
    raw = base64.b64decode(blob)
    return AESGCM(key).decrypt(raw[:12], raw[12:], b"totp").decode()


# ---------------------------------------------------------------------------------------------- recovery codes
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # no 0/O/1/I/L


def new_recovery_codes(n: int = 10) -> list[str]:
    return ["-".join("".join(secrets.choice(ALPHABET) for _ in range(5)) for _ in range(2)) for _ in range(n)]


def normalize_recovery(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch in ALPHABET)


def hash_recovery(code: str, server_secret: str) -> str:
    return hmac.new(server_secret.encode(), b"recovery|" + normalize_recovery(code).encode(), hashlib.sha256).hexdigest()
