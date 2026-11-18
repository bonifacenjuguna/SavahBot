"""WebAuthn / passkey verification, written against the W3C Level 2 steps with `cryptography` and our own tiny CBOR decoder.

Scope, stated plainly: this is for ONE owner on a known site. It requests attestation "none", so it does not check manufacturer
attestation chains (they add nothing for a personal login). Everything that matters for security is checked: challenge, origin,
RP ID hash, user-presence (and optionally user-verification) flags, the signature, and the signature counter."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import struct
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa

from .cbor import CborError, decode, decode_prefix

FLAG_UP, FLAG_UV, FLAG_BE, FLAG_BS, FLAG_AT, FLAG_ED = 0x01, 0x04, 0x08, 0x10, 0x40, 0x80


class WebAuthnError(ValueError):
    """Raised with a message that is safe to show the owner."""


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except Exception as exc:
        raise WebAuthnError("Malformed data from the browser.") from exc


def new_challenge() -> str:
    return b64u(secrets.token_bytes(32))


@dataclass
class Registered:
    credential_id: bytes
    public_key: bytes      # COSE key, exactly as the authenticator sent it
    sign_count: int
    aaguid: str
    backup_eligible: bool
    backup_state: bool
    user_verified: bool


def _client_data(raw: bytes, expected_type: str, challenge: str, origins: list[str]) -> bytes:
    try:
        cd = json.loads(raw.decode())
    except Exception as exc:
        raise WebAuthnError("The browser sent unreadable data.") from exc
    if cd.get("type") != expected_type:
        raise WebAuthnError("Wrong kind of request. Start again.")
    if not hmac.compare_digest(str(cd.get("challenge", "")), challenge):
        raise WebAuthnError("This request is stale or was not started here. Start again.")
    if cd.get("origin") not in origins:
        raise WebAuthnError("This sign-in came from a different site than expected. Check WEBAUTHN_ORIGINS.")
    if cd.get("crossOrigin") is True:
        raise WebAuthnError("Cross-origin passkey requests are refused.")
    return hashlib.sha256(raw).digest()


def _parse_auth_data(auth: bytes, rp_id: str, require_uv: bool) -> tuple[int, int, bytes]:
    if len(auth) < 37:
        raise WebAuthnError("Authenticator data is too short.")
    if not hmac.compare_digest(auth[:32], hashlib.sha256(rp_id.encode()).digest()):
        raise WebAuthnError("This passkey belongs to a different site (RP ID mismatch). Check WEBAUTHN_RP_ID.")
    flags = auth[32]
    if not flags & FLAG_UP:
        raise WebAuthnError("The passkey did not confirm that you were present.")
    if require_uv and not flags & FLAG_UV:
        raise WebAuthnError("The passkey did not verify you (PIN, fingerprint or face). Use a passkey that does.")
    return flags, struct.unpack(">I", auth[33:37])[0], auth[37:]


def verify_registration(client_data_json: bytes, attestation_object: bytes, challenge: str, origins: list[str], rp_id: str,
                        require_uv: bool = False) -> Registered:
    cd_hash = _client_data(client_data_json, "webauthn.create", challenge, origins)
    del cd_hash  # attestation statements are not verified (see module docstring)
    try:
        att = decode(attestation_object)
        auth = att["authData"]
    except (CborError, KeyError, TypeError) as exc:
        raise WebAuthnError("The passkey registration could not be read.") from exc
    flags, count, rest = _parse_auth_data(auth, rp_id, require_uv)
    if not flags & FLAG_AT or len(rest) < 18:
        raise WebAuthnError("The passkey did not include a new credential.")
    aaguid, cred_len = rest[:16], struct.unpack(">H", rest[16:18])[0]
    if cred_len == 0 or cred_len > 1023 or len(rest) < 18 + cred_len:
        raise WebAuthnError("The credential id is invalid.")
    cred_id = rest[18:18 + cred_len]
    try:
        key, used = decode_prefix(rest[18 + cred_len:])
    except CborError as exc:
        raise WebAuthnError("The passkey's public key could not be read.") from exc
    cose = rest[18 + cred_len:18 + cred_len + used]
    public_key(cose)    # raises if it is not a key type we can verify with
    return Registered(cred_id, cose, count, str(aaguid.hex()), bool(flags & FLAG_BE), bool(flags & FLAG_BS), bool(flags & FLAG_UV))


def public_key(cose: bytes) -> Any:
    try:
        k = decode(cose)
        kty, alg = k[1], k[3]
        if kty == 2 and alg == -7 and k[-1] == 1:
            return ec.EllipticCurvePublicNumbers(int.from_bytes(k[-2], "big"), int.from_bytes(k[-3], "big"), ec.SECP256R1()).public_key()
        if kty == 3 and alg == -257:
            return rsa.RSAPublicNumbers(int.from_bytes(k[-2], "big"), int.from_bytes(k[-1], "big")).public_key()
        if kty == 1 and alg == -8 and k[-1] == 6:
            return ed25519.Ed25519PublicKey.from_public_bytes(k[-2])
    except (CborError, KeyError, TypeError, ValueError, IndexError) as exc:
        raise WebAuthnError("This passkey uses a key format that is not supported.") from exc
    raise WebAuthnError("This passkey uses an algorithm that is not supported (need ES256, RS256 or EdDSA).")


def verify_assertion(client_data_json: bytes, authenticator_data: bytes, signature: bytes, challenge: str, origins: list[str], rp_id: str,
                     cose_key: bytes, stored_count: int, require_uv: bool = False) -> tuple[int, bool]:
    """Return (new sign count, user_verified). Raises WebAuthnError on anything wrong, including a counter that went backwards."""
    cd_hash = _client_data(client_data_json, "webauthn.get", challenge, origins)
    flags, count, _ = _parse_auth_data(authenticator_data, rp_id, require_uv)
    key, signed = public_key(cose_key), authenticator_data + cd_hash
    try:
        if isinstance(key, ec.EllipticCurvePublicKey):
            key.verify(signature, signed, ec.ECDSA(hashes.SHA256()))
        elif isinstance(key, rsa.RSAPublicKey):
            key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
        else:
            key.verify(signature, signed)
    except InvalidSignature as exc:
        raise WebAuthnError("The passkey's signature did not check out.") from exc
    if (count or stored_count) and count <= stored_count:
        raise WebAuthnError("This passkey's usage counter went backwards. It may have been cloned, so it was refused.")
    return count, bool(flags & FLAG_UV)
