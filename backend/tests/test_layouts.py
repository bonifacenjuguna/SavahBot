"""Page layouts: save, reset, export and import, and what is refused."""
from app.api.layout_routes import clean_layouts, clean_order

from test_api import e2e


def test_clean_order_keeps_valid_unique_ids():
    assert clean_order(["a", "b", "a", "Bad Id", "../x", 5, "c_1"]) == ["a", "b", "c_1"]
    assert clean_order("nope") == [] and clean_order(None) == []
    assert len(clean_order([f"c{i}" for i in range(100)])) == 40


def test_clean_layouts_drops_unknown_pages_and_kinds():
    out = clean_layouts({"desktop": {"desk": ["a", "b"], "secret": ["x"]}, "tablet": {"desk": ["z"]}, "mobile": {"weather": []}})
    assert out == {"desktop": {"desk": ["a", "b"]}, "mobile": {}}


@e2e
async def test_save_reset_export_import(api):
    st, body = await api.call("GET", "/api/layouts")
    assert st == 200 and body["layouts"] == {"desktop": {}, "mobile": {}} and "desk" in body["pages"]

    st, body = await api.call("POST", "/api/layouts/save", {"kind": "desktop", "page": "desk", "order": ["status", "chat", "chat", "live"]})
    assert st == 200 and body["layouts"]["desktop"]["desk"] == ["status", "chat", "live"]
    await api.call("POST", "/api/layouts/save", {"kind": "mobile", "page": "desk", "order": ["chat", "status"]})
    await api.call("POST", "/api/layouts/save", {"kind": "desktop", "page": "weather", "order": ["now", "week"]})

    # the two layouts are independent and persist
    st, body = await api.call("GET", "/api/layouts")
    assert body["layouts"]["mobile"]["desk"] == ["chat", "status"] and body["layouts"]["desktop"]["desk"] == ["status", "chat", "live"]

    # refused: unknown page, unknown kind, extra fields
    assert (await api.call("POST", "/api/layouts/save", {"kind": "desktop", "page": "security", "order": ["a"]}))[0] == 400
    assert (await api.call("POST", "/api/layouts/save", {"kind": "tablet", "page": "desk", "order": ["a"]}))[0] == 400
    assert (await api.call("POST", "/api/layouts/save", {"kind": "desktop", "page": "desk", "order": ["a"], "x": 1}))[0] == 422
    assert (await api.call("POST", "/api/layouts/save", {"kind": "desktop", "page": "desk", "order": ["a"]}, auth=False))[0] == 401

    # export carries both layouts
    st, exp = await api.call("GET", "/api/layouts/export")
    assert st == 200 and exp["format"] == "savahbot-layouts" and exp["layouts"]["mobile"]["desk"] == ["chat", "status"]

    # selective reset: only the desktop layout of the desk page
    st, body = await api.call("POST", "/api/layouts/reset", {"pages": ["desk"], "kinds": ["desktop"]})
    assert st == 200 and body["reset"] == 1
    assert "desk" not in body["layouts"]["desktop"] and body["layouts"]["mobile"]["desk"] == ["chat", "status"] and "weather" in body["layouts"]["desktop"]

    # reset everything
    st, body = await api.call("POST", "/api/layouts/reset", {})
    assert body["layouts"] == {"desktop": {}, "mobile": {}}

    # import restores what the export held, and rejects other files
    st, body = await api.call("POST", "/api/layouts/import", {"data": exp})
    assert st == 200 and body["imported"] == 3 and body["layouts"]["desktop"]["weather"] == ["now", "week"]
    assert (await api.call("POST", "/api/layouts/import", {"data": {"format": "other", "layouts": {}}}))[0] == 400
    assert (await api.call("POST", "/api/layouts/import", {"data": {"format": "savahbot-layouts", "layouts": {"desktop": {"nope": ["a"]}}}}))[0] == 400
