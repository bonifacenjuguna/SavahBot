import io
import zipfile

from tests.test_api import e2e


@e2e
async def test_reader_rules_roundtrip_and_validation(api):
    st, r = await api.call("GET", "/api/reader/rules")
    assert st == 200 and r["who"] == "everyone" and r["skip_links"] is True
    st, r = await api.call("POST", "/api/reader/rules", {"who": "mods", "users": {"u1": {"mode": "never", "name": "Sam"}}, "dictionary": [{"from": "gg", "to": "good game"}, {"from": "", "to": "x"}]})
    assert st == 200 and r["dictionary"] == [{"from": "gg", "to": "good game"}]
    assert (await api.call("GET", "/api/reader/rules"))[1]["users"]["u1"]["mode"] == "never"
    assert (await api.call("POST", "/api/reader/rules", {"who": "nobody"}))[0] == 422
    assert (await api.call("POST", "/api/reader/rules", {"users": {"u": {"mode": "loud"}}}))[0] == 422


@e2e
async def test_voice_host_and_packs_status(api):
    st, v = await api.call("GET", "/api/voices")
    assert st == 200 and v["packs"] == [] and "volume_hint" in v and v["max_mb"] > 0
    assert (await api.call("POST", "/api/voices/host", {"url": "http://insecure.example.com"}))[0] == 422
    assert (await api.call("POST", "/api/voices/host", {"url": "https://voices.example.com/pack/"}))[1]["host"] == "https://voices.example.com/pack"
    assert (await api.call("POST", "/api/voices/delete", {"pack": "../x"}))[0] == 400
