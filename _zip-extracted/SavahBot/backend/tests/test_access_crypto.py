"""Security primitives: hashing, TOTP (RFC 6238 vectors), recovery codes, CBOR, WebAuthn with a simulated authenticator, QR codes."""
import base64
import hashlib
import json
import struct

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa

from app.access import hashing, qr, totp, webauthn
from app.access.cbor import CborError, decode, decode_prefix


# ------------------------------------------------------------------ hashing
def test_password_hash_roundtrip_and_format():
    h = hashing.hash_password("correct horse battery")
    assert h.startswith(("scrypt$", "$argon2")) and "correct" not in h
    assert hashing.verify_password("correct horse battery", h)
    assert not hashing.verify_password("wrong", h) and not hashing.verify_password("x", "") and not hashing.verify_password("x", "garbage")
    assert hashing.hash_password("same") != hashing.hash_password("same")           # salted
    assert not hashing.needs_rehash(h)
    assert hashing.check_strength("short") and hashing.check_strength("aaaaaaaaaaaa") and not hashing.check_strength("Tr1cky-passphrase")


# ------------------------------------------------------------------ TOTP
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode().rstrip("=")


def test_totp_matches_rfc6238_vectors_and_blocks_replay():
    assert totp.code_at(RFC_SECRET, 59) == "287082"            # RFC 6238 appendix B, SHA-1, last 6 of 94287082
    assert totp.code_at(RFC_SECRET, 1111111109) == "081804"
    assert totp.code_at(RFC_SECRET, 2000000000) == "279037"
    c = totp.verify(RFC_SECRET, "287082", now=59)
    assert c == 1 and totp.verify(RFC_SECRET, "287 082", now=59) == 1   # spaces tolerated
    assert totp.verify(RFC_SECRET, "287082", now=59, last_counter=1) is None   # same code twice is refused
    assert totp.verify(RFC_SECRET, "287082", now=59 + 30) == 1                 # one step of clock drift is fine
    assert totp.verify(RFC_SECRET, "287082", now=59 + 90) is None
    assert totp.verify(RFC_SECRET, "12345", now=59) is None and totp.verify(RFC_SECRET, "abcdef", now=59) is None


def test_totp_secret_sealing_and_uri():
    s = totp.new_secret()
    assert len(s) == 32 and totp.unseal("srv", totp.seal("srv", s)) == s
    with pytest.raises(Exception):
        totp.unseal("other", totp.seal("srv", s))
    assert totp.otpauth_uri(s, "owner@x", "Savah Bot").startswith("otpauth://totp/Savah%20Bot:owner%40x?secret=")


def test_recovery_codes():
    codes = totp.new_recovery_codes()
    assert len(set(codes)) == 10 and all(len(c) == 11 and c[5] == "-" for c in codes)
    assert totp.hash_recovery(codes[0], "s") == totp.hash_recovery(codes[0].lower().replace("-", " "), "s")
    assert totp.hash_recovery(codes[0], "s") != totp.hash_recovery(codes[1], "s")


# ------------------------------------------------------------------ CBOR
def enc(v):
    def head(major, n):
        if n < 24: return bytes([major << 5 | n])
        if n < 256: return bytes([major << 5 | 24, n])
        if n < 65536: return bytes([major << 5 | 25]) + n.to_bytes(2, "big")
        return bytes([major << 5 | 26]) + n.to_bytes(4, "big")
    if isinstance(v, bool): return b"\xf5" if v else b"\xf4"
    if isinstance(v, int): return head(0, v) if v >= 0 else head(1, -1 - v)
    if isinstance(v, bytes): return head(2, len(v)) + v
    if isinstance(v, str): return head(3, len(v.encode())) + v.encode()
    if isinstance(v, list): return head(4, len(v)) + b"".join(enc(x) for x in v)
    if isinstance(v, dict): return head(5, len(v)) + b"".join(enc(k) + enc(x) for k, x in v.items())
    raise TypeError(v)


def test_cbor_decoder():
    v = {"fmt": "none", "n": [1, -7, 300, True], 3: b"\x01\x02", -1: {"a": 70000}}
    assert decode(enc(v)) == v
    assert decode_prefix(enc(v) + b"junk")[1] == len(enc(v))
    for bad in (b"", b"\xa1", b"\x5f", b"\x18", enc(v) + b"x"):
        with pytest.raises(CborError):
            decode(bad)


# ------------------------------------------------------------------ WebAuthn with a simulated authenticator
RP, ORIGIN = "dash.example.app", "https://dash.example.app"


class Authenticator:
    """Plays the browser plus the passkey device."""

    def __init__(self, kind="es256", uv=True):
        self.kind, self.uv, self.count = kind, uv, 0
        self.cred_id = hashlib.sha256(kind.encode()).digest()
        if kind == "es256":
            self.key = ec.generate_private_key(ec.SECP256R1())
            n = self.key.public_key().public_numbers()
            self.cose = enc({1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})
        elif kind == "rs256":
            self.key = rsa.generate_private_key(65537, 2048)
            n = self.key.public_key().public_numbers()
            self.cose = enc({1: 3, 3: -257, -1: n.n.to_bytes(256, "big"), -2: n.e.to_bytes(3, "big")})
        else:
            self.key = ed25519.Ed25519PrivateKey.generate()
            raw = self.key.public_key().public_bytes_raw()
            self.cose = enc({1: 1, 3: -8, -1: 6, -2: raw})

    def flags(self, at=False):
        return 0x01 | (0x04 if self.uv else 0) | (0x40 if at else 0)

    def register(self, challenge, origin=ORIGIN, rp=RP):
        auth = hashlib.sha256(rp.encode()).digest() + bytes([self.flags(True)]) + struct.pack(">I", 0) + b"\0" * 16 + \
            struct.pack(">H", len(self.cred_id)) + self.cred_id + self.cose
        cd = json.dumps({"type": "webauthn.create", "challenge": challenge, "origin": origin}).encode()
        return cd, enc({"fmt": "none", "attStmt": {}, "authData": auth})

    def sign(self, data):
        if self.kind == "es256": return self.key.sign(data, ec.ECDSA(hashes.SHA256()))
        if self.kind == "rs256": return self.key.sign(data, padding.PKCS1v15(), hashes.SHA256())
        return self.key.sign(data)

    def assert_(self, challenge, origin=ORIGIN, rp=RP, count=None, typ="webauthn.get"):
        self.count = self.count + 1 if count is None else count
        auth = hashlib.sha256(rp.encode()).digest() + bytes([self.flags()]) + struct.pack(">I", self.count)
        cd = json.dumps({"type": typ, "challenge": challenge, "origin": origin}).encode()
        return cd, auth, self.sign(auth + hashlib.sha256(cd).digest())


@pytest.mark.parametrize("kind", ["es256", "rs256", "ed25519"])
def test_webauthn_register_then_login(kind):
    dev = Authenticator(kind)
    ch = webauthn.new_challenge()
    reg = webauthn.verify_registration(*dev.register(ch), ch, [ORIGIN], RP, require_uv=True)
    assert reg.credential_id == dev.cred_id and reg.public_key == dev.cose and reg.user_verified
    ch2 = webauthn.new_challenge()
    count, uv = webauthn.verify_assertion(*dev.assert_(ch2), ch2, [ORIGIN], RP, reg.public_key, 0, require_uv=True)
    assert count == 1 and uv


def test_webauthn_rejects_every_kind_of_wrong():
    dev = Authenticator()
    ch = webauthn.new_challenge()
    cd, att = dev.register(ch)
    reg = webauthn.verify_registration(cd, att, ch, [ORIGIN], RP)
    key = reg.public_key
    bad = webauthn.WebAuthnError
    with pytest.raises(bad): webauthn.verify_registration(cd, att, webauthn.new_challenge(), [ORIGIN], RP)              # wrong challenge
    with pytest.raises(bad): webauthn.verify_registration(*dev.register(ch, origin="https://evil.example"), ch, [ORIGIN], RP)  # wrong origin
    with pytest.raises(bad): webauthn.verify_registration(*dev.register(ch, rp="evil.example"), ch, [ORIGIN], RP)        # wrong RP id
    with pytest.raises(bad): webauthn.verify_registration(Authenticator(uv=False).register(ch)[0], Authenticator(uv=False).register(ch)[1], ch, [ORIGIN], RP, require_uv=True)
    c2 = webauthn.new_challenge()
    cd2, auth, sig = dev.assert_(c2)
    with pytest.raises(bad): webauthn.verify_assertion(cd2, auth, sig, webauthn.new_challenge(), [ORIGIN], RP, key, 0)   # replayed challenge
    with pytest.raises(bad): webauthn.verify_assertion(cd2, auth, sig[:-1] + bytes([sig[-1] ^ 1]), c2, [ORIGIN], RP, key, 0)  # bad signature
    with pytest.raises(bad): webauthn.verify_assertion(cd2, auth, sig, c2, ["https://other.app"], RP, key, 0)             # wrong origin list
    with pytest.raises(bad): webauthn.verify_assertion(*dev.assert_(c2, typ="webauthn.create"), c2, [ORIGIN], RP, key, 0)  # wrong type
    other = Authenticator()
    with pytest.raises(bad): webauthn.verify_assertion(*other.assert_(c2), c2, [ORIGIN], RP, key, 0)                       # someone else's key
    # sign counter must go forward once it is in use
    assert webauthn.verify_assertion(*dev.assert_(c2, count=5), c2, [ORIGIN], RP, key, 4)[0] == 5
    with pytest.raises(bad): webauthn.verify_assertion(*dev.assert_(c2, count=5), c2, [ORIGIN], RP, key, 5)
    assert webauthn.verify_assertion(*dev.assert_(c2, count=0), c2, [ORIGIN], RP, key, 0)[0] == 0   # synced passkeys keep a zero counter


# ------------------------------------------------------------------ QR
def test_qr_decodes_with_opencv():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    detectors = [cv2.QRCodeDetector()] + ([cv2.QRCodeDetectorAruco()] if hasattr(cv2, "QRCodeDetectorAruco") else [])

    def decodes(m, text):                      # OpenCV's detector is picky about scale, so a correct code is tried at a few sizes
        n, b = len(m), 4
        for scale in (4, 6, 8):
            img = np.full(((n + 2 * b) * scale,) * 2, 255, np.uint8)
            for r in range(n):
                for c in range(n):
                    if m[r][c]:
                        img[(r + b) * scale:(r + b + 1) * scale, (c + b) * scale:(c + b + 1) * scale] = 0
            if any(d.detectAndDecode(img)[0] == text for d in detectors):
                return True
        return False
    for text in ("hi", totp.otpauth_uri(totp.new_secret(), "owner@example.com", "SavahBot"), "x" * 190, "https://dash.example.app/?a=1&b=%20"):
        assert decodes(qr.encode(text), text)
    assert qr.svg("hello").startswith("<svg")
    with pytest.raises(ValueError):
        qr.encode("y" * 400)
