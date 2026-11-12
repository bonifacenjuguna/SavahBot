"""Firebase Cloud Messaging (HTTP v1) sender, built on the standard library and `cryptography`.

The service account stays on the server. We sign a short-lived JWT with its private key, trade it for an OAuth access
token, and cache that token until shortly before it expires. Nothing from here is ever returned by an API route.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from ..http import NetworkError, request_json

logger = logging.getLogger("savahbot.notify.fcm")

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@dataclass
class SendResult:
    ok: bool
    retry: bool = False          # a later attempt may work (network, 429, 5xx, auth refreshed)
    dead_token: bool = False     # Firebase says this device token is no longer valid: delete it
    error: str = ""
    code: str = ""


def parse_credentials(project_id: str, client_email: str, private_key: str, blob: str) -> tuple[str, str, str]:
    """Accepts the two separate variables, or the whole JSON (plain or base64). Returns (project, email, key) or blanks."""
    blob = (blob or "").strip()
    if blob:
        try:
            raw = blob if blob.startswith("{") else base64.b64decode(blob).decode()
            d = json.loads(raw)
            project_id = project_id or str(d.get("project_id", ""))
            client_email = client_email or str(d.get("client_email", ""))
            private_key = private_key or str(d.get("private_key", ""))
        except (ValueError, TypeError):
            logger.warning("FIREBASE_SERVICE_ACCOUNT_JSON could not be read; it is ignored")
    private_key = (private_key or "").replace("\\n", "\n").strip().strip('"')
    return (project_id or "").strip(), (client_email or "").strip(), private_key


class Fcm:
    def __init__(self, project_id: str = "", client_email: str = "", private_key: str = "", blob: str = "") -> None:
        self.project, self.email, self._pem = parse_credentials(project_id, client_email, private_key, blob)
        self._token = ""
        self._token_exp = 0.0
        self.last_error = ""
        self.last_ok = 0.0
        self._key: Any = None

    @property
    def configured(self) -> bool:
        return bool(self.project and self.email and self._pem)

    def problems(self) -> list[str]:
        out = []
        if not self.project:
            out.append("FIREBASE_PROJECT_ID is not set.")
        if not self.email:
            out.append("FIREBASE_CLIENT_EMAIL is not set.")
        if not self._pem:
            out.append("FIREBASE_PRIVATE_KEY is not set.")
        elif "BEGIN" not in self._pem:
            out.append("FIREBASE_PRIVATE_KEY does not look like a PEM key (it should start with -----BEGIN PRIVATE KEY-----).")
        return out

    def _load_key(self) -> Any:
        if self._key is None:
            self._key = serialization.load_pem_private_key(self._pem.encode(), password=None)
        return self._key

    def _assertion(self, now: float) -> str:
        head = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
        claims = _b64(json.dumps({"iss": self.email, "scope": SCOPE, "aud": TOKEN_URL, "iat": int(now), "exp": int(now) + 3300}, separators=(",", ":")).encode())
        signing = f"{head}.{claims}".encode()
        sig = self._load_key().sign(signing, padding.PKCS1v15(), hashes.SHA256())
        return f"{head}.{claims}.{_b64(sig)}"

    async def access_token(self, force: bool = False) -> str:
        now = time.time()
        if self._token and now < self._token_exp - 120 and not force:
            return self._token
        status, data = await request_json("POST", TOKEN_URL, form={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": self._assertion(now)}, timeout=15)
        if status != 200 or not isinstance(data, dict) or "access_token" not in data:
            reason = (data or {}).get("error_description") or (data or {}).get("error") if isinstance(data, dict) else ""
            raise RuntimeError(f"Google refused the Firebase service account ({status}) {reason or ''}".strip())
        self._token = str(data["access_token"])
        self._token_exp = now + float(data.get("expires_in", 3300))
        return self._token

    async def check(self) -> dict[str, Any]:
        """Proves the service account works without sending anything: a validate-only send to a fake token."""
        if not self.configured:
            return {"ok": False, "problems": self.problems()}
        try:
            token = await self.access_token(force=True)
        except RuntimeError as exc:
            return {"ok": False, "problems": [str(exc)]}
        except (ValueError, TypeError) as exc:
            return {"ok": False, "problems": [f"The private key could not be read: {type(exc).__name__}. Check FIREBASE_PRIVATE_KEY."]}
        except NetworkError as exc:
            return {"ok": False, "problems": [f"Could not reach Google: {exc}"]}
        status, data = await request_json("POST", SEND_URL.format(project=self.project), json_body={"validate_only": True, "message": {"token": "check", "data": {"x": "1"}}},
                                          headers={"Authorization": f"Bearer {token}"}, timeout=15)
        err = _error_code(data)
        if status == 200 or err in ("INVALID_ARGUMENT", "UNREGISTERED"):
            return {"ok": True, "problems": []}     # the fake token is rejected, which proves the project and credentials work
        if status == 404:
            return {"ok": False, "problems": ["Firebase project not found. Check FIREBASE_PROJECT_ID."]}
        if status in (401, 403):
            return {"ok": False, "problems": ["The service account is not allowed to send. In Google Cloud enable 'Firebase Cloud Messaging API' and give it the 'Firebase Cloud Messaging Admin' role."]}
        return {"ok": False, "problems": [f"Firebase answered {status} {err}".strip()]}

    async def send(self, token: str, payload: dict[str, Any]) -> SendResult:
        """`payload` holds title, body, route, tag, priority and category; everything goes in `data` so our worker shows it."""
        if not self.configured:
            return SendResult(False, error="Firebase is not configured")
        # Always "high": with "normal" urgency a phone in battery saving (Doze) may hold the message for a minute or more, while a computer
        # gets it at once. Every SavahBot alert is something the owner wants to see now, and the server already limits how many are sent.
        message = {
            "token": token,
            "data": {k: str(v) for k, v in payload.items() if v is not None},
            "webpush": {"headers": {"Urgency": "high", "TTL": str(int(payload.get("ttl", 86400)))}},
            "android": {"priority": "HIGH", "ttl": f"{int(payload.get('ttl', 86400))}s"},
            "apns": {"headers": {"apns-priority": "10"}},
        }
        for attempt in (0, 1):
            try:
                access = await self.access_token(force=attempt == 1)
                status, data = await request_json("POST", SEND_URL.format(project=self.project), json_body={"message": message}, headers={"Authorization": f"Bearer {access}"}, timeout=15)
            except NetworkError as exc:
                self.last_error = f"network: {exc}"
                return SendResult(False, retry=True, error=self.last_error)
            except (RuntimeError, ValueError, TypeError) as exc:
                self.last_error = str(exc)
                return SendResult(False, retry=isinstance(exc, RuntimeError) and "(5" in str(exc), error=self.last_error)
            if status == 200:
                self.last_ok, self.last_error = time.time(), ""
                return SendResult(True)
            code = _error_code(data)
            if status == 401 and attempt == 0:
                continue                                  # token expired early: fetch a new one and try once more
            if code in ("UNREGISTERED",):
                return SendResult(False, dead_token=True, error="device token no longer registered", code=code)
            if code == "INVALID_ARGUMENT" and "token" in json.dumps(data).lower():
                return SendResult(False, dead_token=True, error="device token invalid", code=code)
            self.last_error = f"Firebase {status} {code}".strip()
            return SendResult(False, retry=status in (429, 500, 502, 503, 504) or code in ("UNAVAILABLE", "INTERNAL", "QUOTA_EXCEEDED"), error=self.last_error, code=code)
        return SendResult(False, retry=True, error="authentication failed")


def _error_code(data: Any) -> str:
    try:
        err = data["error"]
        for d in err.get("details", []) or []:
            if d.get("errorCode"):
                return str(d["errorCode"])
        return str(err.get("status", ""))
    except (TypeError, KeyError, AttributeError):
        return ""
