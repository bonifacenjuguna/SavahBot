from datetime import datetime, timedelta

import pytest

from app.security import LoginThrottle, sign_token, verify_token
from app.timeparse import ReminderParseError, next_repeat, parse_duration, parse_reminder

NOW = datetime(2026, 11, 2, 8, 40)  # 11:40 in Nairobi (UTC+3)
TZ = "Africa/Nairobi"


def test_durations():
    assert parse_duration("30m") == 1800
    assert parse_duration("2h30m") == 9000
    assert parse_duration("1d") == 86400
    assert parse_duration("soon") is None


def test_relative_reminder():
    r = parse_reminder("30m stretch your legs", TZ, NOW)
    assert r.due_utc == NOW + timedelta(minutes=30) and r.text == "stretch your legs" and r.repeat == "none"


def test_clock_time_uses_owner_timezone():
    r = parse_reminder("18:30 call mom", TZ, NOW)
    assert r.due_utc == datetime(2026, 11, 2, 15, 30)
    r2 = parse_reminder("09:00 standup", TZ, NOW)  # already passed today -> tomorrow
    assert r2.due_utc == datetime(2026, 11, 3, 6, 0)


def test_tomorrow_and_dates():
    assert parse_reminder("tomorrow 09:00 pay rent", TZ, NOW).due_utc == datetime(2026, 11, 3, 6, 0)
    assert parse_reminder("2026-11-05 14:00 dentist", TZ, NOW).due_utc == datetime(2026, 11, 5, 11, 0)


def test_repeating_reminders():
    d = parse_reminder("daily 08:00 plan the stream", TZ, NOW)
    assert d.repeat == "daily" and d.due_utc == datetime(2026, 11, 3, 5, 0)
    e = parse_reminder("every 2h drink water", TZ, NOW)
    assert e.repeat == "interval" and e.interval_seconds == 7200
    assert next_repeat(datetime(2026, 11, 2, 8, 0), "interval", 7200, NOW) == datetime(2026, 11, 2, 10, 0)
    assert next_repeat(datetime(2026, 11, 1, 5, 0), "daily", None, NOW) == datetime(2026, 11, 3, 5, 0)
    assert next_repeat(NOW, "none", None, NOW) is None


@pytest.mark.parametrize("bad", ["", "soon", "25:99 x", "today 07:00 passed", "2020-01-01 10:00 old", "30m", "every 10s x"])
def test_bad_input_is_rejected_with_a_message(bad):
    with pytest.raises(ReminderParseError):
        parse_reminder(bad, TZ, NOW)


def test_token_roundtrip_tamper_and_expiry():
    tok = sign_token("s3cret", {"sub": "owner", "exp": 2000})
    assert verify_token("s3cret", tok, now=1000)["sub"] == "owner"
    assert verify_token("s3cret", tok, now=3000) is None
    assert verify_token("other", tok, now=1000) is None
    body, sig = tok.split(".")
    assert verify_token("s3cret", body + "x." + sig, now=1000) is None
    assert verify_token("s3cret", "garbage", now=1000) is None


def test_login_throttle_locks_and_recovers():
    t = LoginThrottle(max_attempts=3, lockout_seconds=60)
    for _ in range(3):
        t.fail("1.2.3.4", now=0)
    assert t.retry_after("1.2.3.4", now=10) > 0
    assert t.retry_after("5.6.7.8", now=10) == 0
    assert t.retry_after("1.2.3.4", now=100) == 0
    t.fail("1.2.3.4", now=100)
    t.success("1.2.3.4")
    assert t.retry_after("1.2.3.4", now=101) == 0
