"""Sign-in and Security Centre over real HTTP: any-two-of-three, step-up, recovery, passkeys, sessions, lockdown."""
import time

from app.access import totp
from app.access.webauthn import b64u
from test_access_crypto import Authenticator
from test_api import PASSWORD, Api, e2e


async def code_for(api, offset=0):
    row = await api.c.db.fetchone("SELECT secret FROM access_totp WHERE id = 1")
    return totp.code_at(totp.unseal(api.c._secret_for_tests, row["secret"]), time.time() + offset)


async def login(api, password=PASSWORD):
    return await api.call("POST", "/api/auth/login", {"password": password}, auth=False)


async def step_up(api):
    assert (await api.call("POST", "/api/security/step-up", {"method": "password", "code": PASSWORD}))[0] == 200


async def enrol_totp(api):
    await step_up(api)
    st, b = await api.call("POST", "/api/security/totp/begin")
    assert st == 200 and b["qr"].startswith("<svg") and b["uri"].startswith("otpauth://") and len(b["secret"]) == 32
    api.c._secret_for_tests = api.c.access._secret
    st, done = await api.call("POST", "/api/security/totp/confirm", {"code": totp.code_at(b["secret"], time.time())})
    assert st == 200 and len(done["recovery_codes"]) == 10
    return b["secret"], done["recovery_codes"]


@e2e
async def test_password_only_until_a_second_method_exists_and_password_is_never_plaintext(api):
    assert api.token.startswith("sbs_")
    assert await api.c.db.kv_get("_owner_password") in ("", None)
    assert (await api.c.db.kv_get("_owner_password_hash")).startswith(("scrypt$", "$argon2"))
    st, b = await login(api)
    assert st == 200 and b["setup_needed"] and b["token"].startswith("sbs_")
    st, ov = await api.call("GET", "/api/security/overview")
    assert st == 200 and not ov["enforced"] and ov["readiness"]["score"] < 100
    assert (await api.call("POST", "/api/auth/login", {"password": "wrong"}, auth=False))[0] == 401
    # sign out really kills the session on the server
    other = Api(api.base, b["token"])
    assert (await other.call("GET", "/api/auth/me"))[0] == 200
    assert (await other.call("POST", "/api/auth/logout"))[0] == 200
    assert (await other.call("GET", "/api/auth/me"))[0] == 401


@e2e
async def test_sensitive_actions_need_a_fresh_confirmation(api):
    api.c.access._secret_for_tests = api.c.access._secret
    await api.c.db.execute("UPDATE access_sessions SET step_up_until = 0")
    st, b = await api.call("POST", "/api/security/totp/begin")
    assert st == 403 and b["code"] == "step_up_required"
    assert (await api.call("POST", "/api/security/step-up", {"method": "password", "code": "nope"}))[0] == 401
    await step_up(api)
    assert (await api.call("POST", "/api/security/totp/begin"))[0] == 200


@e2e
async def test_any_two_of_three_after_totp_is_enrolled(api):
    secret, recovery = await enrol_totp(api)
    st, ov = await api.call("GET", "/api/security/overview")
    assert ov["enforced"] and ov["totp"] and ov["recovery_left"] == 10
    # password alone no longer signs anyone in
    st, b = await login(api)
    assert st == 200 and b["step"] == "more" and "token" not in b and "totp" in b["methods"]
    ticket = b["ticket"]
    # a wrong code is refused, the right one (next time slot, so it is not the one used at setup) finishes it
    assert (await api.call("POST", "/api/auth/factor", {"ticket": ticket, "method": "totp", "code": "000000"}, auth=False))[0] == 401
    st, ok = await api.call("POST", "/api/auth/factor", {"ticket": ticket, "method": "totp", "code": totp.code_at(secret, time.time() + 30)}, auth=False)
    assert st == 200 and ok["token"].startswith("sbs_") and set(ok["factors"]) == {"password", "totp"}
    # the same code cannot be replayed
    st, b = await login(api)
    assert (await api.call("POST", "/api/auth/factor", {"ticket": b["ticket"], "method": "totp", "code": totp.code_at(secret, time.time() + 30)}, auth=False))[0] == 401
    # a recovery code works once
    st, b = await login(api)
    assert (await api.call("POST", "/api/auth/factor", {"ticket": b["ticket"], "method": "recovery", "code": recovery[0].lower()}, auth=False))[0] == 200
    st, b = await login(api)
    assert (await api.call("POST", "/api/auth/factor", {"ticket": b["ticket"], "method": "recovery", "code": recovery[0]}, auth=False))[0] == 401
    st, ov = await api.call("GET", "/api/security/overview")
    assert ov["recovery_left"] == 9
    # a ticket cannot be used with a made-up value
    assert (await api.call("POST", "/api/auth/factor", {"ticket": "x" * 20, "method": "totp", "code": "123456"}, auth=False))[0] == 401
    # you cannot remove your way back down to one method
    await step_up(api)
    assert (await api.call("DELETE", "/api/security/totp"))[0] == 409


@e2e
async def test_passkey_registration_and_every_pairing(api):
    secret, _ = await enrol_totp(api)
    dev = Authenticator("es256")
    await step_up(api)
    st, opts = await api.call("POST", "/api/security/passkeys/options")
    assert st == 200 and opts["publicKey"]["rp"]["id"] == "dash.example.app"
    cd, att = dev.register(opts["publicKey"]["challenge"])
    cred = {"id": b64u(dev.cred_id), "response": {"clientDataJSON": b64u(cd), "attestationObject": b64u(att)}}
    assert (await api.call("POST", "/api/security/passkeys/register", {"ticket": opts["ticket"], "credential": cred, "name": "Test phone"}))[0] == 200
    assert (await api.call("POST", "/api/security/passkeys/register", {"ticket": opts["ticket"], "credential": cred}))[0] == 400   # one use only

    async def passkey_step(ticket=""):
        st, o = await api.call("POST", "/api/auth/passkey/options", {"ticket": ticket}, auth=False)
        assert st == 200
        cd_, auth_, sig = dev.assert_(o["publicKey"]["challenge"])
        c = {"id": b64u(dev.cred_id), "response": {"clientDataJSON": b64u(cd_), "authenticatorData": b64u(auth_), "signature": b64u(sig)}}
        return await api.call("POST", "/api/auth/passkey/verify", {"ticket": o["ticket"], "credential": c}, auth=False)

    st, r = await passkey_step()                                # passkey alone: not enough
    assert st == 200 and r["step"] == "more" and "password" in r["methods"] and "token" not in r
    st, b = await login(api)                                    # password then passkey
    st, r = await passkey_step(b["ticket"])
    assert st == 200 and set(r["factors"]) == {"password", "passkey"}
    st, r = await passkey_step()                                # passkey then totp
    st, r = await api.call("POST", "/api/auth/factor", {"ticket": r["ticket"], "method": "totp", "code": totp.code_at(secret, time.time() + 30)}, auth=False)
    assert st == 200 and set(r["factors"]) == {"passkey", "totp"}
    # a signature from a different device is refused
    other = Authenticator("es256")
    st, o = await api.call("POST", "/api/auth/passkey/options", {}, auth=False)
    cd_, auth_, sig = other.assert_(o["publicKey"]["challenge"])
    bad = {"id": b64u(dev.cred_id), "response": {"clientDataJSON": b64u(cd_), "authenticatorData": b64u(auth_), "signature": b64u(sig)}}
    assert (await api.call("POST", "/api/auth/passkey/verify", {"ticket": o["ticket"], "credential": bad}, auth=False))[0] == 401
    # with three methods one may go, then the floor of two holds
    await step_up(api)
    assert (await api.call("DELETE", "/api/security/totp"))[0] == 200
    st, ov = await api.call("GET", "/api/security/overview")
    pid = ov["passkeys"][0]["id"]
    assert (await api.call("DELETE", f"/api/security/passkeys/{pid}"))[0] == 409


@e2e
async def test_change_password_sessions_activity_and_lockdown(api):
    st, other = await login(api)
    o = Api(api.base, other["token"])
    st, s = await api.call("GET", "/api/security/sessions")
    assert st == 200 and len(s["sessions"]) == 2 and sum(x["current"] for x in s["sessions"]) == 1 and all("id" not in x for x in s["sessions"])
    assert (await api.call("POST", "/api/security/password", {"current": "nope", "new": "A-brand-new-pass-1"}))[0] == 401
    assert (await api.call("POST", "/api/security/password", {"current": PASSWORD, "new": "short"}))[0] == 400
    st, r = await api.call("POST", "/api/security/password", {"current": PASSWORD, "new": "A-brand-new-pass-1"})
    assert st == 200 and r["signed_out_elsewhere"] == 1
    assert (await o.call("GET", "/api/auth/me"))[0] == 401
    assert (await login(api))[0] == 401 and (await login(api, "A-brand-new-pass-1"))[0] == 200
    st, act = await api.call("GET", "/api/security/activity")
    assert st == 200 and any(a["action"] == "password_changed" for a in act["audit"]) and any(e["kind"] == "login_failed" for e in act["events"])
    # lockdown: other sessions die at once, this one can only reach the Security page, lifting needs a fresh confirmation
    st, third = await login(api, "A-brand-new-pass-1")
    t = Api(api.base, third["token"])
    assert (await api.call("POST", "/api/security/lockdown", {"on": True}))[0] == 200
    assert (await t.call("GET", "/api/auth/me"))[0] == 401
    assert (await api.call("GET", "/api/status"))[0] == 403
    assert (await api.call("GET", "/api/security/overview"))[1]["lockdown"] is True
    await api.c.db.execute("UPDATE access_sessions SET step_up_until = 0")
    st, b = await api.call("POST", "/api/security/lockdown", {"on": False})
    assert st == 403 and b["code"] == "step_up_required"
    assert (await api.call("POST", "/api/security/step-up", {"method": "password", "code": "A-brand-new-pass-1"}))[0] == 200
    assert (await api.call("POST", "/api/security/lockdown", {"on": False}))[0] == 200
    assert (await api.call("GET", "/api/status"))[0] == 200
