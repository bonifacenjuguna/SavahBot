"""1.3.6 hardening: the client address behind a proxy, the sign-in lockout, response headers, and the OAuth callback page."""
from types import SimpleNamespace

from starlette.requests import Request

from app.api.routes import client_ip
from app.http import request_json, request_raw
from test_api import PASSWORD, e2e


def _request(forwarded: str | None, peer: str = "10.0.0.1", hops: int = 1) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded is not None else []
    app = SimpleNamespace(state=SimpleNamespace(c=SimpleNamespace(settings=SimpleNamespace(trusted_proxy_hops=hops))))
    return Request({"type": "http", "headers": headers, "client": (peer, 5555), "app": app})


def test_client_ip_trusts_only_what_our_own_proxy_added():
    # A client can write anything at the START of X-Forwarded-For; the proxy appends the real address at the END.
    assert client_ip(_request("6.6.6.6, 203.0.113.9")) == "203.0.113.9"
    assert client_ip(_request("a, b, c, 203.0.113.9")) == "203.0.113.9"
    assert client_ip(_request("203.0.113.9")) == "203.0.113.9"
    assert client_ip(_request(None)) == "10.0.0.1"                      # no header: the connection itself
    assert client_ip(_request("")) == "10.0.0.1"
    assert client_ip(_request("6.6.6.6, 203.0.113.9", hops=2)) == "6.6.6.6"       # two proxies in front: the second from the right
    assert client_ip(_request("203.0.113.9", hops=2)) == "10.0.0.1"               # fewer entries than proxies: the header is not trusted at all
    assert client_ip(_request("6.6.6.6, 203.0.113.9", hops=0)) == "10.0.0.1"      # no proxy: the header is ignored
    assert len(client_ip(_request("x" * 500))) <= 64


@e2e
async def test_lockout_cannot_be_dodged_with_a_forged_forwarded_for(api):
    async def attempt(forwarded: str, password: str):
        return await request_json("POST", api.base + "/api/auth/login", json_body={"password": password}, headers={"X-Forwarded-For": forwarded})

    for i in range(5):       # a different made-up address in front each time, the same real one (added by the proxy) behind it
        assert (await attempt(f"10.1.1.{i}, 203.0.113.50", "wrong"))[0] == 401
    st, body = await attempt("10.1.1.99, 203.0.113.50", PASSWORD)
    assert st == 429, body                                              # locked out even with the right password
    st, body = await attempt("10.1.1.99, 198.51.100.7", PASSWORD)       # another real client is not affected
    assert st == 200 and body["token"].startswith("sbs_")


@e2e
async def test_api_answers_are_not_cacheable_and_not_sniffed(api):
    st, _, headers = await request_raw("GET", api.base + "/api/health")
    h = {k.lower(): v for k, v in headers.items()}
    assert st == 200 and h["cache-control"] == "no-store" and h["x-content-type-options"] == "nosniff" and h["referrer-policy"] == "no-referrer"
    st, _, headers = await request_raw("GET", api.base + "/")
    assert "cache-control" not in {k.lower() for k in headers}           # only API paths are marked no-store


@e2e
async def test_sign_out_closes_the_session_on_the_server(api):
    st, b = await api.call("POST", "/api/auth/login", {"password": PASSWORD}, auth=False)
    token = b["token"]
    hdr = {"Authorization": f"Bearer {token}"}
    assert (await request_json("GET", api.base + "/api/status", headers=hdr))[0] == 200
    assert (await request_json("POST", api.base + "/api/auth/logout", json_body={}, headers=hdr))[0] == 200
    assert (await request_json("GET", api.base + "/api/status", headers=hdr))[0] == 401      # the copied token no longer works


@e2e
async def test_oauth_callback_page_never_echoes_markup(api):
    object.__setattr__(api.c.settings, "frontend_url", "")            # no dashboard address: the callback answers with a small page of its own
    evil = "<script>alert(1)</script><img src=x onerror=alert(2)>"
    st, raw, headers = await request_raw("GET", api.base + "/api/youtube/oauth/callback", params={"error": evil}, follow_redirects=False)
    body = raw.decode()
    assert st == 200 and "<script>" not in body and "<img" not in body and "&lt;script&gt;" in body
    assert "default-src 'none'" in {k.lower(): v for k, v in headers.items()}["content-security-policy"]
