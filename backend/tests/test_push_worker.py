"""Pins the behaviour of frontend/public/sw.js that once broke silently: the Send test button did nothing while the dashboard was open."""
import re
from pathlib import Path

SW = (Path(__file__).resolve().parents[2] / "frontend" / "public" / "sw.js").read_text(encoding="utf8")
BADGE = Path(__file__).resolve().parents[2] / "frontend" / "public" / "badge-96.png"


def test_test_notification_shows_even_when_dashboard_is_focused():
    assert 'if (watching && p.category !== "test.test") {' in SW


def test_a_suppressed_push_still_shows_a_silent_placeholder_that_is_removed_at_once():
    """Chrome adds its own grey "SavahBot" notification when a push shows nothing. So the suppressed branch shows a silent one and closes it."""
    handler = SW[SW.index('addEventListener("push"'):SW.index('addEventListener("notificationclick"')]
    quiet = handler[handler.index('if (watching'):handler.index("await self.registration.showNotification(p.title, {\n        body: p.body")]
    assert "silent: true" in quiet and "showNotification" in quiet and ".close()" in quiet and "savahbot-quiet" in quiet
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
