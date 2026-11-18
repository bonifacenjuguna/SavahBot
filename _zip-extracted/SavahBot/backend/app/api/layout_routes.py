"""Page layouts (1.4.0): the order of the cards on Desk, Insights, Notifications and Weather.

Two layouts are kept per page, "desktop" (wide screens) and "mobile" (phones and tablets), so arranging one never disturbs the other.
Only the order of stable card ids is stored. A card that is not in the saved order (a new one) is placed at the end by the dashboard,
and an id that no longer exists is ignored, so a saved layout can never hide a card.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request

from .routes import ApiError, R, parse

KEY = "ui_layouts"
PAGES = ("desk", "moderation", "insights", "notifications", "weather")
KINDS = ("desktop", "mobile")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,39}$")
MAX_CARDS = 40
FORMAT = "savahbot-layouts"


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Save(_In):
    kind: str
    page: str
    order: list[str] = Field(max_length=MAX_CARDS)


class Reset(_In):
    pages: list[str] = Field(default_factory=list, max_length=len(PAGES))      # empty means every page
    kinds: list[str] = Field(default_factory=list, max_length=len(KINDS))      # empty means both layouts


class Import(_In):
    data: dict[str, Any]


def clean_order(order: Any) -> list[str]:
    """Keeps valid, unique card ids in their order. Anything else is dropped."""
    out: list[str] = []
    if isinstance(order, list):
        for x in order:
            if isinstance(x, str) and ID_RE.match(x) and x not in out:
                out.append(x)
            if len(out) >= MAX_CARDS:
                break
    return out


def clean_layouts(raw: Any) -> dict[str, dict[str, list[str]]]:
    """The whole stored or imported value, reduced to known layout kinds and known pages."""
    out: dict[str, dict[str, list[str]]] = {k: {} for k in KINDS}
    if isinstance(raw, dict):
        for kind in KINDS:
            part = raw.get(kind)
            if isinstance(part, dict):
                for page in PAGES:
                    order = clean_order(part.get(page))
                    if order:
                        out[kind][page] = order
    return out


def _check(kind: str | None = None, page: str | None = None) -> None:
    if kind is not None and kind not in KINDS:
        raise ApiError("Layout must be desktop or mobile.", 400)
    if page is not None and page not in PAGES:
        raise ApiError("That page does not have a movable layout.", 400)


async def load(c: Any) -> dict[str, dict[str, list[str]]]:
    raw = await c.db.kv_get(KEY)
    try:
        return clean_layouts(json.loads(raw) if raw else {})
    except ValueError:
        return clean_layouts({})


async def store(c: Any, layouts: dict[str, dict[str, list[str]]]) -> None:
    await c.db.kv_set(KEY, json.dumps(clean_layouts(layouts), separators=(",", ":")))


@R.add("/layouts", ["GET"])
async def layouts_get(request: Request, c: Any) -> dict:
    return {"layouts": await load(c), "pages": list(PAGES), "kinds": list(KINDS)}


@R.add("/layouts/save", ["POST"])
async def layouts_save(request: Request, c: Any) -> dict:
    b = await parse(request, Save)
    _check(b.kind, b.page)
    order = clean_order(b.order)
    cur = await load(c)
    if order:
        cur[b.kind][b.page] = order
    else:
        cur[b.kind].pop(b.page, None)
    await store(c, cur)
    await c.activity.record("settings", "layout", f"Arranged the {b.page} page ({b.kind})", "routine")
    return {"layouts": cur}


@R.add("/layouts/reset", ["POST"])
async def layouts_reset(request: Request, c: Any) -> dict:
    b = await parse(request, Reset)
    for p in b.pages:
        _check(page=p)
    for k in b.kinds:
        _check(kind=k)
    pages, kinds = (b.pages or list(PAGES)), (b.kinds or list(KINDS))
    cur = await load(c)
    n = 0
    for k in kinds:
        for p in pages:
            n += 1 if cur[k].pop(p, None) is not None else 0
    await store(c, cur)
    await c.activity.record("settings", "layout", f"Reset {n} page layout{'s' if n != 1 else ''}", "routine")
    return {"layouts": cur, "reset": n}


@R.add("/layouts/export", ["GET"])
async def layouts_export(request: Request, c: Any) -> dict:
    """A plain file with both layouts. It holds card names and their order only: nothing private."""
    return {"format": FORMAT, "version": 1, "exported": int(time.time()), "layouts": await load(c)}


@R.add("/layouts/import", ["POST"])
async def layouts_import(request: Request, c: Any) -> dict:
    """Replaces the layouts of every page the file contains. Pages and layout kinds the file does not mention are left alone."""
    b = await parse(request, Import)
    if b.data.get("format") != FORMAT:
        raise ApiError("This is not a SavahBot layouts file.", 400)
    incoming = clean_layouts(b.data.get("layouts"))
    cur = await load(c)
    n = 0
    for k in KINDS:
        for p, order in incoming[k].items():
            cur[k][p] = order
            n += 1
    if n == 0:
        raise ApiError("The file has no layouts for the pages that can be arranged.", 400)
    await store(c, cur)
    await c.activity.record("settings", "layout", f"Imported {n} page layout{'s' if n != 1 else ''}", "notable")
    return {"layouts": cur, "imported": n}
