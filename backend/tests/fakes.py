"""Scriptable local HTTP servers that stand in for Telegram and YouTube/Google in tests."""
import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class FakeServer:
    """handler(method, path, query, body, headers) -> (status, json_or_None). Every request is recorded."""

    def __init__(self, handler):
        self.requests = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def _do(self, method):
                u = urlparse(self.path)
                query = {k: v[0] for k, v in parse_qs(u.query).items()}
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                ctype = self.headers.get("Content-Type", "")
                if "json" in ctype and raw:
                    body = json.loads(raw)
                elif "form" in ctype and raw:
                    body = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
                else:
                    body = None
                rec = {"method": method, "path": u.path, "query": query, "body": body, "auth": self.headers.get("Authorization")}
                outer.requests.append(rec)
                status, data = handler(method, u.path, query, body, dict(self.headers))
                payload = b"" if data is None else json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                self._do("GET")

            def do_POST(self):
                self._do("POST")

            def do_DELETE(self):
                self._do("DELETE")

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.srv.server_port}"

    def calls(self, path_part, method=None):
        return [r for r in self.requests if path_part in r["path"] and (method is None or r["method"] == method)]

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


class FakeTelegram:
    TOKEN = "123456:FAKE-TOKEN-abc"

    def __init__(self):
        self.updates = []
        self.fail_with = None  # (status, description)
        self.server = FakeServer(self._handle)

    def _handle(self, method, path, query, body, headers):
        if f"/bot{self.TOKEN}/" not in path:
            return 404, {"ok": False, "description": "Not Found"}
        name = path.rsplit("/", 1)[1]
        if self.fail_with:
            return self.fail_with[0], {"ok": False, "description": self.fail_with[1]}
        if name == "getMe":
            return 200, {"ok": True, "result": {"id": 1, "is_bot": True, "username": "SavahTestBot"}}
        if name == "getUpdates":
            if self.updates:
                out, self.updates = self.updates, []
                return 200, {"ok": True, "result": out}
            time.sleep(0.05)
            return 200, {"ok": True, "result": []}
        return 200, {"ok": True, "result": True if name != "sendMessage" else {"message_id": 99}}

    @property
    def base(self):
        return self.server.base

    def sent(self):
        return [r["body"] for r in self.server.calls("/sendMessage")]

    def texts(self):
        return [b["text"] for b in self.sent()]


def tg_message(user_id, text, chat_id=None, chat_type="private"):
    return {"update_id": int(time.time() * 1000) % 10**9, "message": {"message_id": 1, "from": {"id": user_id}, "chat": {"id": chat_id or user_id, "type": chat_type}, "text": text}}


async def wait_for(cond, timeout=5.0, step=0.01):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        await asyncio.sleep(step)
    return cond()
