"""The `.svbak` file format: authenticated, chunked AES-256-GCM.

    SVBAK1\\n | header length (4 bytes) | header (JSON) | chunk, chunk, ...      chunk = length (4) | nonce (12) | ciphertext+tag

* The key is 256 random bits, shown to you ONCE as `SVK1-XXXX-...`. SavahBot never stores it, only a short fingerprint.
* An optional passphrase is mixed in (scrypt then HKDF), so the file needs both.
* Every chunk has its own random nonce. The authenticated extra data binds each chunk to the header, its position and whether
  it is the last one, so reordering, dropping, truncating or editing chunks (or the header) makes decryption fail.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import secrets
import struct
import time
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC = b"SVBAK1\n"
CHUNK = 1024 * 1024
MAX_HEADER = 16 * 1024
MAX_PLAIN = 400 * 1024 * 1024
KEY_PREFIX = "SVK1-"


class BackupError(ValueError):
    """A message that is safe to show the owner."""


# ---------------------------------------------------------------------------------------------- keys
def new_key() -> bytes:
    return secrets.token_bytes(32)


def format_key(key: bytes) -> str:
    raw = base64.b32encode(key + hashlib.sha256(key).digest()[:2]).decode().rstrip("=")
    return KEY_PREFIX + "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))


def parse_key(text: str) -> bytes:
    t = "".join((text or "").split()).upper()
    if t.startswith(KEY_PREFIX.rstrip("-")):
        t = t[len(KEY_PREFIX.rstrip("-")):]
    t = t.replace("-", "")
    try:
        raw = base64.b32decode(t + "=" * (-len(t) % 8))
    except Exception as exc:
        raise BackupError("That key is not written correctly. Copy it again exactly as it was shown.") from exc
    if len(raw) != 34 or hashlib.sha256(raw[:32]).digest()[:2] != raw[32:]:
        raise BackupError("That key has a typo or is incomplete. Check it character by character.")
    return raw[:32]


def _derive(key: bytes, passphrase: str, salt: bytes) -> bytes:
    ikm = key
    if passphrase:
        ikm = key + hashlib.scrypt(passphrase.encode(), salt=salt, n=2 ** 15, r=8, p=1, dklen=32, maxmem=128 * 1024 * 1024)
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b"savahbot-backup-v1").derive(ikm)


def fingerprint(final_key: bytes) -> str:
    h = hashlib.sha256(b"fp|" + final_key).hexdigest()[:12]
    return "-".join(h[i:i + 4] for i in range(0, 12, 4))


# ---------------------------------------------------------------------------------------------- seal / open
def _aad(header_bytes: bytes, index: int, last: bool) -> bytes:
    return hashlib.sha256(header_bytes).digest() + struct.pack(">QB", index, int(last))


def seal(plain: bytes, key: bytes, passphrase: str = "", meta: dict[str, Any] | None = None) -> tuple[bytes, str]:
    """Encrypt `plain`. Returns (file bytes, fingerprint)."""
    salt = secrets.token_bytes(16)
    final = _derive(key, passphrase, salt)
    header = {"v": 1, "created": int(time.time()), "chunk": CHUNK, "salt": base64.b64encode(salt).decode(), "pass": bool(passphrase),
              "fp": fingerprint(final), **(meta or {})}
    hb = json.dumps(header, separators=(",", ":"), sort_keys=True).encode()
    out = io.BytesIO()
    out.write(MAGIC + struct.pack(">I", len(hb)) + hb)
    aes = AESGCM(final)
    pieces = [plain[i:i + CHUNK] for i in range(0, len(plain), CHUNK)] or [b""]
    for i, piece in enumerate(pieces):
        nonce = secrets.token_bytes(12)
        ct = aes.encrypt(nonce, piece, _aad(hb, i, i == len(pieces) - 1))
        out.write(struct.pack(">I", len(ct)) + nonce + ct)
    return out.getvalue(), header["fp"]


def read_header(data: bytes) -> tuple[dict[str, Any], bytes, int]:
    if not data.startswith(MAGIC):
        raise BackupError("That is not a SavahBot backup file.")
    pos = len(MAGIC)
    if len(data) < pos + 4:
        raise BackupError("The file is cut short.")
    (n,) = struct.unpack(">I", data[pos:pos + 4])
    if n > MAX_HEADER or len(data) < pos + 4 + n:
        raise BackupError("The file is damaged (header).")
    hb = data[pos + 4:pos + 4 + n]
    try:
        header = json.loads(hb)
        if header.get("v") != 1:
            raise BackupError("This backup was made by a newer version of SavahBot. Update first.")
    except ValueError as exc:
        raise BackupError("The file is damaged (header).") from exc
    return header, hb, pos + 4 + n


def open_(data: bytes, key: bytes, passphrase: str = "") -> tuple[bytes, dict[str, Any]]:
    header, hb, pos = read_header(data)
    if header.get("pass") and not passphrase:
        raise BackupError("This backup was made with a passphrase. Enter it too.")
    final = _derive(key, passphrase if header.get("pass") else "", base64.b64decode(header["salt"]))
    if fingerprint(final) != header.get("fp"):
        raise BackupError("The key (or passphrase) does not match this backup.")
    aes, out, index = AESGCM(final), io.BytesIO(), 0
    while pos < len(data):
        if pos + 4 + 12 > len(data):
            raise BackupError("The file is cut short.")
        (n,) = struct.unpack(">I", data[pos:pos + 4])
        if n < 16 or n > CHUNK + 16:
            raise BackupError("The file is damaged (chunk size).")
        nonce, ct = data[pos + 4:pos + 16], data[pos + 16:pos + 16 + n]
        if len(ct) != n:
            raise BackupError("The file is cut short.")
        pos += 16 + n
        try:
            out.write(aes.decrypt(nonce, ct, _aad(hb, index, pos >= len(data))))
        except InvalidTag as exc:
            raise BackupError("The file was changed, damaged or cut short, so it was not opened.") from exc
        index += 1
        if out.tell() > MAX_PLAIN:
            raise BackupError("The backup is larger than the safety limit.")
    if index == 0:
        raise BackupError("The backup has no data.")
    return out.getvalue(), header
