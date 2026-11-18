"""Async JSON-over-HTTP helper built on the standard library (urllib in a worker thread).

No third-party HTTP client is needed. Environment proxies are honoured automatically.
`request_json` returns (status, data) for ANY HTTP status; it raises NetworkError only when no HTTP
response was received at all (DNS failure, refused, timeout).
"""
from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class NetworkError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D401
        return None


def _sync_request(method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float,
                  max_bytes: int, follow_redirects: bool) -> tuple[int, bytes, dict[str, str]]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    opener = urllib.request.build_opener() if follow_redirects else urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read(max_bytes), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        try:
            data = exc.read(max_bytes)
        except Exception:
            data = b""
        return exc.code, data, dict(exc.headers or {})
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise NetworkError(f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}") from exc


async def request_raw(method: str, url: str, *, params: dict[str, Any] | None = None,
                      json_body: Any = None, form: dict[str, Any] | None = None,
                      headers: dict[str, str] | None = None, timeout: float = 10.0,
                      max_bytes: int = 2_000_000, follow_redirects: bool = True) -> tuple[int, bytes, dict[str, str]]:
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    hdrs = {"User-Agent": "SavahBot/1.0", "Accept": "application/json, text/plain;q=0.9, */*;q=0.5"}
    hdrs.update(headers or {})
    body: bytes | None = None
    if json_body is not None:
        body = json.dumps(json_body).encode()
        hdrs["Content-Type"] = "application/json"
    elif form is not None:
        body = urllib.parse.urlencode(form).encode()
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    return await asyncio.to_thread(_sync_request, method.upper(), url, hdrs, body, timeout, max_bytes, follow_redirects)


async def request_json(method: str, url: str, **kwargs: Any) -> tuple[int, Any]:
    status, raw, _ = await request_raw(method, url, **kwargs)
    if not raw:
        return status, None
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw.decode("utf-8", "replace")
