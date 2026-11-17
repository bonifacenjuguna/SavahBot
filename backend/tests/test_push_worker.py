"""Pins the behaviour of frontend/public/sw.js that once broke silently: the Send test button did nothing while the dashboard was open."""
import re
from pathlib import Path

SW = (Path(__file__).resolve().parents[2] / "frontend" / "public" / "sw.js").read_text(encoding="utf8")
BADGE = Path(__file__).resolve().parents[2] / "frontend" / "public" / "badge-96.png"


def test_test_notification_shows_even_when_dashboard_is_focused():
    assert 'if (watching && p.category !== "test.test") {' in SW


def test_a_suppressed_push_still_shows_a_silent_placeholder_that_stays_until_the_event_ends():
    """Chrome adds its own grey "SavahBot" notification when a push shows nothing. So the suppressed branch shows a silent one and does NOT close it inside the push event (1.4.9: Chrome counts the visible
    notifications when the event ends, so closing it after 50 ms brought the grey one back). The dashboard closes it later (push.ts)."""
    handler = SW[SW.index('addEventListener("push"'):SW.index('addEventListener("notificationclick"')]
    quiet = handler[handler.index('if (watching'):handler.index("await self.registration.showNotification(p.title, {\n        body: p.body")]
    assert "silent: true" in quiet and "showNotification" in quiet and ".close()" not in quiet and "savahbot-quiet" in quiet
    assert "finally" in handler                                                   # and a failure partway still ends in a visible notification


def test_ordinary_foreground_push_is_still_suppressed_and_background_push_shows():
    handler = SW[SW.index('addEventListener("push"'):SW.index('addEventListener("notificationclick"')]
    assert "watching" in handler and "showNotification" in handler
    assert handler.index("if (watching") < handler.index("showNotification")        # suppressed only before the alert is shown
    assert "notify-push" in handler                                                # the bell and toast still hear about it


def test_a_push_without_content_still_shows_something_so_chrome_adds_no_generic_one():
    assert "readPayload(event) ||" in SW


def test_click_handling_and_route_safety_are_intact():
    assert "notify-click" in SW and "safeRoute" in SW and "openWindow" in SW


def test_status_bar_badge_is_a_transparent_white_silhouette_not_a_solid_square():
    from PIL import Image
    assert '"/badge-96.png"' in SW and BADGE.exists()
    im = Image.open(BADGE).convert("RGBA")
    px = list(im.getdata())
    assert 0.05 < sum(1 for p in px if p[3] > 0) / len(px) < 0.5          # a shape, not a filled square
    assert all(p[:3] == (255, 255, 255) for p in px if p[3] > 200)


def test_system_alert_is_hidden_only_when_dashboard_is_visible_and_focused():
    """1.3.7 loosened this to "visible" alone and phones stopped showing push. The page pops up its own toast only under the same test (visible and focused), so one of the two always fires."""
    handler = SW[SW.index('addEventListener("push"'):SW.index('addEventListener("notificationclick"')]
    assert 'c.visibilityState === "visible" && c.focused' in handler
    notes = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "notifications.ts").read_text(encoding="utf8")
    assert 'document.visibilityState === "visible" && document.hasFocus()' in notes


# ------------------------------------------------------------------ 1.4.11
def test_an_update_waits_for_the_page_instead_of_swapping_in_under_a_session():
    install = SW[SW.index('addEventListener("install"'):SW.index('addEventListener("activate"')]
    assert "if (!self.registration.active) return self.skipWaiting()" in install        # only the very first install starts at once
    assert 'event.data.type === "skip-waiting"' in SW and "self.skipWaiting()" in SW


def test_the_worker_never_touches_the_api_or_authenticated_requests():
    fetch_handler = SW[SW.index('addEventListener("fetch"'):SW.index("// ------------------------------------------------------------------------------------------------ push")]
    assert 'request.method !== "GET"' in fetch_handler and "url.origin !== self.location.origin || sensitive(request, url)" in fetch_handler
    sensitive = SW[SW.index("function sensitive"):]
    sensitive = sensitive[:sensitive.index("\n}")]
    assert 'url.pathname.startsWith("/api/")' in sensitive and 'request.headers.has("authorization")' in sensitive      # same-origin /api/ and signed requests stay out
    assert 'startsWith("/assets/")' in fetch_handler                                       # the only thing it keeps: the build's own hashed files
    assert "respondWith" in fetch_handler and "Authorization" not in fetch_handler


def test_approval_buttons_use_only_the_signed_link_never_the_sign_in_token():
    block = SW[SW.index("async function decide"):SW.index("// ------------------------------------------------------------------------------------------------ Background Sync")]
    assert '"/api/notify/act"' in block and "JSON.stringify({ token: atk, verb })" in block
    assert "Authorization" not in block and "replay" not in block
    assert "ACT_TOKEN.test(atk)" in SW[SW.index('addEventListener("notificationclick"'):SW.index("async function setBadge") if "async function setBadge" in SW else None]
    assert 'actions: p.atk ? [{ action: "approve"' in SW


def test_background_sync_sends_saved_writes_once_and_drops_refused_ones():
    block = SW[SW.index("async function replay"):SW.index("// ------------------------------------------------------------------------------------------------ Periodic")]
    assert block.index('s.delete(item.id)') < block.index("fetch(")                       # taken out first, so it can never be sent twice
    assert "res.status >= 500 || res.status === 401 || res.status === 429" in block        # not delivered: back in the queue
    assert 'self.navigator.locks.request("savahbot-outbox-flush"' in block                 # the page and the worker never send at the same moment
    assert 'event.tag === "savahbot-outbox"' in SW and 'event.tag !== "savahbot-badge"' in SW


def test_the_badge_link_can_only_read_the_waiting_count():
    block = SW[SW.index('addEventListener("periodicsync"'):]
    assert "/api/notify/badge?t=" in block and 'method: "POST"' not in block and "Authorization" not in block


def test_the_manifest_declares_the_installed_app_capabilities():
    import json
    m = json.loads((Path(__file__).resolve().parents[2] / "frontend" / "public" / "manifest.webmanifest").read_text(encoding="utf8"))
    assert m["display_override"][0] == "window-controls-overlay" and "standalone" in m["display_override"]
    assert m["share_target"] == {"action": "/share", "method": "GET", "params": {"title": "title", "text": "text", "url": "url"}}
    assert m["protocol_handlers"] == [{"protocol": "web+savahbot", "url": "/open?u=%s"}]
    assert m["launch_handler"]["client_mode"][0] == "navigate-existing"
    shots = m["screenshots"]
    assert {s["form_factor"] for s in shots} == {"wide", "narrow"} and len(shots) >= 4
    for s in shots:
        assert (Path(__file__).resolve().parents[2] / "frontend" / "public" / s["src"].lstrip("/")).is_file(), s["src"]
    assert len(m["shortcuts"]) >= 4 and all(s["url"].startswith("/") for s in m["shortcuts"])


# ------------------------------------------------------------------ 1.4.12
def test_the_push_handler_is_one_sequence_that_never_closes_the_notification_it_just_showed():
    """Chrome posts its own grey "SavahBot / Tap to copy the URL for this app" notification when nothing is on screen as a push event ends.
    1.4.11 put a database write before the notification and left a second job closing placeholders at the same time (same tag), so the new one
    was sometimes closed. Now: no separate cleanup job, the notification first, the badge and the cleanup afterwards and never able to stop it."""
    handler = SW[SW.index('addEventListener("push"'):SW.index('addEventListener("notificationclick"')]
    assert handler.count("event.waitUntil(") == 1                                               # no second job running alongside
    assert handler.index("showNotification") < handler.index("setBadge(")                       # the notification first
    assert handler.index("setBadge(") < handler.index("getNotifications(")                      # then the badge, then the leftover cleanup
    assert "if (!placeholder)" in handler                                                       # a placeholder is never closed by its own push
    assert "try { await setBadge(p.pending); } catch" in handler
    assert 'try { await kvPut("pending"' in SW
