"""YouTube live chat: OAuth, a quota governor, live-broadcast detection, chat polling and moderation actions.

The YouTube Data API gives every project 10,000 quota units a day. Reading chat is the biggest recurring
cost, so the governor spreads a share of the daily budget (YT_READ_BUDGET_FRACTION) across the expected
stream length (YOUTUBE_EXPECTED_STREAM_HOURS) and keeps the rest for actions (deletes cost 20, bans 200).
All costs are configurable because Google changes them; verify them in the YouTube docs.
"""
from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from ..http import NetworkError, request_json
from ..models import ChatMessage

logger = logging.getLogger("savahbot.youtube")
CALLBACK_PATH = "/api/youtube/oauth/callback"
CHANNEL_ID_RE = re.compile(r"^UC[0-9A-Za-z_-]{22}$")
PERMISSION_REASONS = ("forbidden", "insufficientPermissions")
PROTECTED_USER_REASONS = ("modificationNotAllowed", "liveChatBanInsertionNotAllowed")
ENDED_REASONS = ("liveChatEnded", "liveChatNotFound", "liveChatDisabled")
QUOTA_REASONS = ("quotaExceeded", "dailyLimitExceeded")
ACTION_PERM = {"chat_delete": "delete", "ban": "ban", "chat_insert": "send"}
ACTION_LABEL = {"chat_delete": "delete messages", "ban": "ban or time out people", "chat_insert": "post messages"}
DENIED_PHRASE = "not allowed to"  # every permission refusal message contains this, so callers (the hub) can stop a batch on it


def parse_video_id(value: str) -> str:
    """Accepts a bare video ID or a watch / youtu.be / live / shorts URL."""
    v = (value or "").strip()
    m = re.search(r"(?:v=|youtu\.be/|/live/|/shorts/|/embed/)([0-9A-Za-z_-]{11})", v)
    return m.group(1) if m else v


# ---------------------------------------------------------------------------------------------
class QuotaTracker:
    """A local estimate of today's YouTube quota. Google does not let an app read its remaining quota (only the Cloud Console
    shows it), so this adds up what SavahBot itself spends. The YouTube loop only runs in live mode, so demo never adds to it. It rolls over at the YouTube reset
    (midnight Pacific) even while nothing is running, and can be corrected by hand with set_used()."""

    def __init__(self, cfg: Any, store: Any, now_fn: Callable[[], float] = time.time) -> None:
        self.cfg = cfg
        self.store = store
        self.now_fn = now_fn
        self._day = ""
        self._stored = 0

    def day(self) -> str:
        return datetime.fromtimestamp(self.now_fn(), ZoneInfo(self.cfg.get("yt_quota_reset_tz"))).strftime("%Y-%m-%d")

    @property
    def _used(self) -> int:
        """Units spent today. Yesterday's number is never shown after the reset, even if nothing has synced yet."""
        return self._stored if self._day == self.day() else 0

    def resets_at(self) -> int:
        """The moment of the next YouTube quota reset, as epoch seconds (midnight in the reset timezone, daylight saving included).
        The dashboard turns this into the owner's own clock time, e.g. 11:00 in Nairobi when Pacific Time is on standard time."""
        tz = ZoneInfo(self.cfg.get("yt_quota_reset_tz"))
        now = datetime.fromtimestamp(self.now_fn(), tz)
        # Build tomorrow's midnight from the calendar date so a 23 or 25 hour day (clock change) cannot shift it.
        tomorrow = now.date() + timedelta(days=1)
        return int(datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=tz).timestamp())

    def resets_in(self) -> int:
        """Seconds until the next YouTube quota reset (midnight in the reset timezone)."""
        return max(0, self.resets_at() - int(self.now_fn()))

    async def sync(self) -> None:
        d = self.day()
        if d != self._day:
            self._day = d
            self._stored = await self.store.quota_get(d)

    async def spend(self, units: int) -> None:
        await self.sync()
        self._stored += units
        await self.store.quota_add(self._day, units)

    async def set_used(self, units: int) -> None:
        """Replace today's estimate, e.g. with the number shown in the Google Cloud Console, or 0 to start the counter again."""
        await self.sync()
        units = max(0, int(units))
        await self.store.quota_add(self._day, units - self._stored)
        self._stored = units

    async def mark_exhausted(self) -> None:
        await self.sync()
        missing = self.cfg.get("yt_daily_quota") - self._used
        if missing > 0:
            self._stored += missing
            await self.store.quota_add(self._day, missing)

    @property
    def used(self) -> int:
        return self._used

    @property
    def remaining(self) -> int:
        return max(0, self.cfg.get("yt_daily_quota") - self._used)

    def cost(self, kind: str) -> int:
        return int(self.cfg.get(f"yt_cost_{kind}"))

    def can_afford(self, kind: str) -> bool:
        return self.remaining >= self.cost(kind)

    def read_interval(self, stream_elapsed: float = 0.0) -> float | None:
        """Seconds to wait between chat polls, or None when only the action reserve is left (stop reading)."""
        daily = self.cfg.get("yt_daily_quota")
        reserve = daily * (1 - self.cfg.get("yt_read_budget_fraction"))
        if self.remaining <= reserve * 0.25:
            return None
        lo, hi = self.cfg.get("yt_min_poll_seconds"), self.cfg.get("yt_max_poll_seconds")
        read_budget_left = daily * self.cfg.get("yt_read_budget_fraction") - self._used
        polls = read_budget_left / max(1, self.cost("chat_list"))
        if polls <= 0:
            return hi  # read budget spent: keep moderating, but slowly, into the action reserve
        remaining_s = max(300.0, self.cfg.get("youtube_expected_stream_hours") * 3600 - stream_elapsed)
        return min(hi, max(lo, remaining_s / polls))

    def status(self) -> dict[str, Any]:
        daily = self.cfg.get("yt_daily_quota")
        return {"used": self._used, "daily": daily, "remaining": self.remaining, "fraction": round(self._used / daily, 4) if daily else 0,
                "day": self.day(), "reset_tz": self.cfg.get("yt_quota_reset_tz"), "resets_at": self.resets_at(), "resets_in": self.resets_in(), "estimate": True}


# ---------------------------------------------------------------------------------------------
@dataclass
class PendingLogin:
    """Tokens from a fresh Google sign-in that have NOT been saved yet. Nothing is committed until the account is checked."""
    access: str
    refresh: str
    expires_at: float


class GoogleAuth:
    def __init__(self, cfg: Any, db: Any, now_fn: Callable[[], float] = time.time) -> None:
        self.cfg = cfg
        self.db = db
        self.now_fn = now_fn
        self._access = ""
        self._expires = 0.0
        self._states: dict[str, float] = {}
        self.last_error = ""
        self.generation = 0  # bumped whenever the saved login changes, so in-flight refreshes can tell they are stale

    async def refresh_token(self) -> str:
        return (await self.db.kv_get("youtube_refresh_token")) or self.cfg.get("youtube_refresh_token") or ""

    async def connected(self) -> bool:
        return bool(self.cfg.get("google_client_id") and self.cfg.get("google_client_secret") and await self.refresh_token())

    def redirect_uri(self) -> str:
        return self.cfg.get("google_redirect_uri") or (self.cfg.public_url + CALLBACK_PATH if self.cfg.public_url else "")

    def new_state(self) -> str:
        now = self.now_fn()
        self._states = {s: t for s, t in self._states.items() if t > now}
        state = secrets.token_urlsafe(24)
        self._states[state] = now + 600
        return state

    def check_state(self, state: str) -> bool:
        exp = self._states.pop(state, 0)
        return exp > self.now_fn()

    def auth_url(self, state: str) -> str:
        return self.cfg.get("google_oauth_auth_url") + "?" + urlencode({
            "client_id": self.cfg.get("google_client_id"), "redirect_uri": self.redirect_uri(), "response_type": "code",
            "scope": self.cfg.get("google_oauth_scope"), "access_type": "offline", "prompt": "consent", "state": state})

    async def begin_login(self, code: str) -> PendingLogin:
        """Exchange the sign-in code for tokens WITHOUT saving or activating anything.

        A new account's access token is never paired with a refresh token that belongs to a previous login: if Google does not
        return a refresh token with this sign-in, the whole sign-in is refused and the existing connection is left untouched."""
        status, data = await request_json("POST", self.cfg.get("google_oauth_token_url"), form={
            "code": code, "client_id": self.cfg.get("google_client_id"), "client_secret": self.cfg.get("google_client_secret"),
            "redirect_uri": self.redirect_uri(), "grant_type": "authorization_code"})
        if status != 200 or not isinstance(data, dict) or not data.get("access_token"):
            raise RuntimeError(f"Google rejected the authorisation code ({(data or {}).get('error_description') or (data or {}).get('error') or status})")
        if not data.get("refresh_token"):
            raise RuntimeError("Google did not return a refresh token for this sign-in, so it was not saved and any existing connection is unchanged. "
                               "Remove SavahBot from the Google account's third-party access (myaccount.google.com/connections) and connect again.")
        return PendingLogin(data["access_token"], data["refresh_token"], self.now_fn() + float(data.get("expires_in", 3600)) - 60)

    async def commit_login(self, p: PendingLogin) -> None:
        """Make a checked sign-in the active connection: refresh token and access token always come from the same login."""
        await self.db.kv_set("youtube_refresh_token", p.refresh)
        self._access, self._expires = p.access, p.expires_at
        self.generation += 1
        self.last_error = ""

    async def exchange_code(self, code: str) -> None:
        """begin + commit in one step (no account check). The OAuth callback uses the two steps with a check in between."""
        await self.commit_login(await self.begin_login(code))

    async def access_token(self, force: bool = False) -> str:
        if not force and self._access and self.now_fn() < self._expires:
            return self._access
        refresh = await self.refresh_token()
        if not refresh or not self.cfg.get("google_client_id"):
            raise RuntimeError("YouTube is not connected")
        gen = self.generation
        try:
            status, data = await request_json("POST", self.cfg.get("google_oauth_token_url"), form={
                "client_id": self.cfg.get("google_client_id"), "client_secret": self.cfg.get("google_client_secret"),
                "refresh_token": refresh, "grant_type": "refresh_token"})
        except NetworkError as exc:
            raise RuntimeError(f"Could not reach Google ({exc})") from None
        if gen != self.generation:  # the login changed while we were asking: this answer belongs to the OLD refresh token, drop it
            return await self.access_token(force)
        if status != 200 or not isinstance(data, dict) or not data.get("access_token"):
            reason = (data or {}).get("error_description") or (data or {}).get("error") or status if isinstance(data, dict) else status
            self.last_error = f"Google refused to refresh the login ({reason}). Reconnect YouTube."
            raise RuntimeError(self.last_error)
        self._access, self._expires = data["access_token"], self.now_fn() + float(data.get("expires_in", 3600)) - 60
        self.last_error = ""
        return self._access

    async def disconnect(self) -> None:
        await self.db.kv_delete("youtube_refresh_token")
        self._access, self._expires = "", 0.0
        self.generation += 1


# ---------------------------------------------------------------------------------------------
def _reason(data: Any) -> str:
    try:
        err = data["error"]
        return (err.get("errors") or [{}])[0].get("reason") or err.get("status") or err.get("message", "")
    except (TypeError, KeyError, AttributeError, IndexError):
        return ""


def parse_item(item: dict[str, Any]) -> ChatMessage | None:
    sn, ad = item.get("snippet") or {}, item.get("authorDetails") or {}
    typ = sn.get("type")
    if typ == "textMessageEvent":
        text = (sn.get("textMessageDetails") or {}).get("messageText") or sn.get("displayMessage") or ""
    elif typ == "superChatEvent":
        text = (sn.get("superChatDetails") or {}).get("userComment") or ""
    else:
        return None  # deletions, bans, memberships, etc. are not chat text
    if not text.strip():
        return None
    level = "owner" if ad.get("isChatOwner") else "mod" if ad.get("isChatModerator") else "member" if ad.get("isChatSponsor") else "everyone"
    try:
        ts = datetime.fromisoformat(sn.get("publishedAt", "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        ts = time.time()
    return ChatMessage(platform="youtube", author_id=ad.get("channelId") or sn.get("authorChannelId", ""),
                       author_name=ad.get("displayName", "unknown"), text=text, level=level, ts=ts, msg_id=item.get("id", ""))


class YouTubeSource:
    name = "youtube"
    IDENTITY_RETRY = 600.0           # how often to re-ask Google who is signed in after a failed lookup (nothing is being enforced)
    IDENTITY_RETRY_EXPECTED = 30.0   # ...and when YOUTUBE_MODERATOR_ACCOUNT is set: monitoring is blocked until this succeeds

    def __init__(self, c: Any) -> None:
        self.c = c
        self.cfg = c.cfg
        self.hub = c.hub
        self.auth: GoogleAuth = c.google
        self.quota: QuotaTracker = c.quota
        self._task: asyncio.Task | None = None
        self.state = "stopped"
        self.chat_id = ""
        self.video_id = ""
        self.title = ""
        self.last_error = ""
        self.last_poll = 0.0
        self.polls = 0
        self._page_token = ""
        self._first_poll = True
        self._stream_started = 0.0
        self._connected_cache = False
        self.account: dict[str, str] | None = None   # the signed-in Google account's own channel (who is moderating)
        self.target: dict[str, str] | None = None    # the channel being moderated (whose live chat is read)
        self.video_channel_id = ""
        self.last_action_error = ""
        self._identity_tried = 0.0
        self._target_raw = ""
        self._detect_day = ""
        self._detect_spent = 0
        # what YouTube itself has answered about this account's permissions (None = never tested; nothing is assumed)
        self.perms: dict[str, bool | None] = {"read": None, "delete": None, "ban": None, "send": None}
        self._denied: dict[str, tuple[float, str]] = {}   # action -> (retry not before, the refusal message)
        self._errors = 0                                   # consecutive failures, for exponential backoff

    def forget_identity(self) -> None:
        """Called when the Google login changes, so the account is looked up again."""
        self.account, self._identity_tried = None, 0.0
        self._detach()

    def _reset_permissions(self) -> None:
        self.perms = {"read": None, "delete": None, "ban": None, "send": None}
        self._denied.clear()

    def _detach(self) -> None:
        if self.chat_id:
            self.hub.stream_state(False)
        self.chat_id, self._page_token, self.title, self.video_id, self.video_channel_id = "", "", "", "", ""
        self._reset_permissions()  # a refusal belongs to one account in one chat: the next attach starts clean

    def _backoff(self) -> float:
        """30 s, 60 s, 120 s ... capped at 5 minutes, for consecutive unexpected failures. A success resets it."""
        self._errors += 1
        return min(300.0, 30.0 * 2 ** (self._errors - 1))

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if self._task is None or self._task.done():
            self.state = "starting"
            self._task = asyncio.ensure_future(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        self.state = "stopped"
        self.chat_id = ""
        self._page_token = ""
        self._reset_permissions()

    def status(self) -> dict[str, Any]:
        return {"state": self.state, "connected": self._connected_cache, "chat_attached": bool(self.chat_id), "video_id": self.video_id,
                "title": self.title, "last_error": self.last_error or self.auth.last_error, "last_poll": self.last_poll or None,
                "polls": self.polls, "quota": self.quota.status(), "redirect_uri": self.auth.redirect_uri(),
                "account": self.account, "target": self.target or self._configured_target(), "target_source": self._target_source(),
                "video_channel_id": self.video_channel_id,
                "last_action_error": self.last_action_error, "permissions": dict(self.perms),
                "denied_for": {k: max(0, round(until - time.time())) for k, (until, _m) in self._denied.items() if until > time.time()},
                "expected_account": (self.cfg.get("youtube_moderator_account") or "").strip()}

    # ------------------------------------------------------------------ HTTP with auth
    async def _api(self, method: str, path: str, *, params: dict[str, Any] | None = None, body: Any = None) -> tuple[int, Any]:
        url = self.cfg.get("youtube_api_base").rstrip("/") + path
        for attempt in (0, 1):
            token = await self.auth.access_token(force=attempt == 1)
            try:
                status, data = await request_json(method, url, params=params, json_body=body, headers={"Authorization": f"Bearer {token}"}, timeout=15)
            except NetworkError as exc:
                raise RuntimeError(f"network error ({exc})") from None
            if status != 401:
                break
        return status, data

    # ------------------------------------------------------------------ main loop
    async def _run(self) -> None:
        wait = 0.0
        while True:
            try:
                await asyncio.sleep(wait)
                wait = await self._step()
            except asyncio.CancelledError:
                raise
            except RuntimeError as exc:
                self.last_error = str(exc)
                self.state = "error"
                wait = self._backoff()
            except Exception:
                logger.exception("YouTube loop error")
                self.last_error = "Unexpected error, see server logs"
                self.state = "error"
                wait = self._backoff()

    async def _step(self) -> float:
        await self.quota.sync()
        self._connected_cache = await self.auth.connected()
        if not self._connected_cache:
            self.state = "not_connected"
            return 5.0
        if not self.chat_id:
            return await self._detect()
        blocked = self._identity_gate()
        if blocked:  # e.g. YOUTUBE_MODERATOR_ACCOUNT was set or changed while a stream was attached
            self._detach()
            self.state, self.last_error = "config_error", blocked
            return 60.0
        return await self._poll()

    # ------------------------------------------------------------------ who is signed in, and which channel is the target
    async def _fetch_account(self) -> tuple[dict[str, str] | None, int]:
        """One lookup of the signed-in account's channel. (None, status) when YouTube did not give a usable answer."""
        if not self.quota.can_afford("channel_list"):
            return None, 0
        await self.quota.spend(self.quota.cost("channel_list"))
        status, data = await self._api("GET", "/channels", params={"part": "id,snippet", "mine": "true"})
        if status in (401, 403) and _reason(data) not in QUOTA_REASONS:
            raise RuntimeError(self._auth_message(status, data))
        if status != 200 or not isinstance(data, dict):
            return None, status
        items = data.get("items") or []
        sn = (items[0].get("snippet") or {}) if items else {}
        return {"channel_id": items[0].get("id", "") if items else "", "title": sn.get("title", ""), "handle": sn.get("customUrl", "")}, status

    async def refresh_identity(self) -> dict[str, str] | None:
        """Looks up the channel of the signed-in Google account. This is the moderator, NOT the channel being moderated.

        If the lookup gives no usable answer the account stays unknown (None); `_identity_gate` then refuses to proceed whenever
        YOUTUBE_MODERATOR_ACCOUNT is set."""
        self._identity_tried = time.time()
        acct, _status = await self._fetch_account()
        if acct is not None:
            self.account = acct
        return self.account

    @staticmethod
    def _auth_message(status: int, data: Any) -> str:
        reason = _reason(data)
        if status == 401:
            return "Google rejected the saved login (it may have been revoked). Press Reconnect Google account on the Setup page."
        return f"YouTube refused the request ({reason or status}). Check that YouTube Data API v3 is enabled and the sign-in has the YouTube permission."

    def _configured_target(self) -> dict[str, str] | None:
        """What YOUTUBE_TARGET_CHANNEL_ID says, shown on the dashboard even before (or without) a live lookup. Display only:
        nothing is attached or moderated from this."""
        raw = (self.cfg.get("youtube_target_channel_id") or self.cfg.get("youtube_channel_id") or "").strip()
        if CHANNEL_ID_RE.match(raw):
            return {"channel_id": raw, "title": ""}
        if raw.startswith("@"):
            return {"channel_id": raw, "title": "(handle: resolved when live)"}
        return None

    def _target_source(self) -> str:
        """Where the target setting comes from. A value saved from the dashboard (for example by the 'Moderate my own channel'
        button) silently beats the Railway variable, so the Setup page shows which one is in force."""
        if "youtube_target_channel_id" in (getattr(self.cfg, "_overrides", None) or {}):
            return "dashboard"
        if self.cfg.get("youtube_target_channel_id"):
            return "env"
        return "legacy" if self.cfg.get("youtube_channel_id") else ""

    def _expected_account(self) -> str:
        return (self.cfg.get("youtube_moderator_account") or "").strip()

    @staticmethod
    def _describe(acct: dict[str, str] | None) -> str:
        acct = acct or {}
        return f"{acct.get('title') or 'an unknown account'} ({acct.get('channel_id') or 'no channel found'})"

    def _mismatch_for(self, acct: dict[str, str]) -> str:
        """'' when `acct` is the account YOUTUBE_MODERATOR_ACCOUNT expects (or nothing is expected), else a message."""
        want = self._expected_account()
        if not want:
            return ""
        have = {acct.get("channel_id", ""), acct.get("handle", "").lower().lstrip("@"), acct.get("handle", "").lower()}
        if want in have or want.lower().lstrip("@") in have:
            return ""
        return f"Signed in as {self._describe(acct)}, but YOUTUBE_MODERATOR_ACCOUNT expects {want}. Disconnect and connect with the right Google account."

    def _moderator_mismatch(self) -> str:
        return self._mismatch_for(self.account) if self.account is not None else ""

    def _identity_gate(self) -> str:
        """'' when monitoring and moderating may go ahead, else why not.

        Fails CLOSED: when YOUTUBE_MODERATOR_ACCOUNT is set, the signed-in account must be known AND match. An identity lookup that
        failed, was skipped or has not happened yet is not a pass. With no expectation configured nothing is checked."""
        if not self._expected_account():
            return ""
        if self.account is None:
            return (f"Could not confirm which Google account is signed in, and YOUTUBE_MODERATOR_ACCOUNT is set to {self._expected_account()}, "
                    "so SavahBot will not monitor or moderate until it can. It keeps trying.")
        return self._mismatch_for(self.account)

    async def _resolve_target(self) -> str:
        """Returns an error message, or '' once self.target holds the channel to moderate."""
        raw = (self.cfg.get("youtube_target_channel_id") or self.cfg.get("youtube_channel_id") or "").strip()
        if not raw:
            self.target = None
            hint = f" You are signed in as {self.account['title']} ({self.account['channel_id']})." if self.account and self.account.get("channel_id") else ""
            return ("No target channel is set, so SavahBot will not guess. Set YOUTUBE_TARGET_CHANNEL_ID to the channel you want moderated "
                    "(your own channel ID if you own it, or the creator's channel ID if you are their appointed moderator)." + hint)
        if self.target and raw == self._target_raw:
            return ""
        if CHANNEL_ID_RE.match(raw):
            self.target, self._target_raw = {"channel_id": raw, "title": ""}, raw
            return ""
        if raw.startswith("@"):
            await self.quota.spend(self.quota.cost("channel_list"))
            status, data = await self._api("GET", "/channels", params={"part": "id,snippet", "forHandle": raw})
            items = (data.get("items") or []) if status == 200 and isinstance(data, dict) else []
            if items:
                self.target = {"channel_id": items[0]["id"], "title": (items[0].get("snippet") or {}).get("title", "")}
                self._target_raw = raw
                return ""
            if status in (401, 403):
                raise RuntimeError(self._auth_message(status, data))
            self.target = None
            return f"YouTube has no channel with the handle {raw}. Use the channel ID (starts with UC) instead."
        self.target = None
        return f"YOUTUBE_TARGET_CHANNEL_ID must be a channel ID (starts with UC, 24 characters) or a @handle, not {raw!r}."

    async def _prepare(self) -> str:
        """Identity and configuration checks that must pass before any stream is attached. Returns an error or ''."""
        if self.account is None and time.time() - self._identity_tried > (self.IDENTITY_RETRY_EXPECTED if self._expected_account() else self.IDENTITY_RETRY):
            await self.refresh_identity()
        return self._identity_gate() or await self._resolve_target()

    # ------------------------------------------------------------------ finding the target's live stream
    def _detect_failure(self, status: int, data: Any, interval: float) -> float | None:
        reason = _reason(data)
        if status == 403 and reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"):
            self.state = "quota_low"
            return 300.0
        if status in (401, 403):
            self.last_error, self.state = self._auth_message(status, data), "error"
            return 60.0
        if status != 200:
            self.last_error, self.state = f"YouTube answered {status} while looking for the stream.", "error"
            return 30.0
        return None

    async def _videos(self, ids: list[str]) -> tuple[int, Any]:
        await self.quota.spend(self.quota.cost("video_list"))
        return await self._api("GET", "/videos", params={"part": "snippet,liveStreamingDetails", "id": ",".join(ids)})

    def _attach(self, item: dict[str, Any]) -> float:
        chat = (item.get("liveStreamingDetails") or {}).get("activeLiveChatId")
        sn = item.get("snippet") or {}
        self.chat_id, self.video_id, self.title = chat, item.get("id", ""), sn.get("title", "")
        self.video_channel_id = sn.get("channelId", "")
        self._page_token, self._first_poll, self.last_error = "", True, ""
        self._stream_started = time.time()
        self.state = "live"
        self.hub.stream_state(True, self.title or "YouTube live stream")
        return 0.0

    async def _detect(self) -> float:
        interval = float(self.cfg.get("youtube_detect_interval_seconds"))
        if not self.quota.can_afford("video_list"):
            self.state = "quota_low"
            return 300.0
        problem = await self._prepare()
        if problem:
            self.state, self.last_error = "config_error", problem
            # while the account is unconfirmed and one is required, look again soon (a transient lookup failure should heal fast)
            return min(60.0, self.IDENTITY_RETRY_EXPECTED) if self.account is None and self._expected_account() else 60.0
        target = self.target["channel_id"]  # type: ignore[index]
        video = parse_video_id(self.cfg.get("youtube_video_id"))
        own = bool(self.account and self.account.get("channel_id") == target)

        if video:
            status, data = await self._videos([video])
            bad = self._detect_failure(status, data, interval)
            if bad is not None:
                return bad
            item = ((data.get("items") or [None])[0]) if isinstance(data, dict) else None
            if not item:
                self.state, self.last_error = "error", f"Video {video} was not found, or this account is not allowed to see it."
                return 60.0
            actual = (item.get("snippet") or {}).get("channelId", "")
            if actual != target:
                self.state = "config_error"
                self.last_error = f"Video {video} belongs to channel {actual or 'unknown'}, not the target channel {target}. SavahBot did not attach to it."
                return 60.0
            if not (item.get("liveStreamingDetails") or {}).get("activeLiveChatId"):
                self.state, self.last_error = "offline", ""
                return interval
            return self._attach(item)

        if not self.cfg.get("youtube_auto_detect_live"):
            self.state, self.last_error = "offline", ""
            return interval

        if own:  # cheap and documented: the account's own active broadcast
            if not self.quota.can_afford("broadcast_list"):
                self.state = "quota_low"
                return 300.0
            await self.quota.spend(self.quota.cost("broadcast_list"))
            status, data = await self._api("GET", "/liveBroadcasts", params={"part": "snippet,status", "broadcastStatus": "active", "broadcastType": "all"})
            bad = self._detect_failure(status, data, interval)
            if bad is not None:
                return bad
            bc = ((data.get("items") or [None])[0]) if isinstance(data, dict) else None
            chat = ((bc or {}).get("snippet") or {}).get("liveChatId")
            if not bc or not chat:
                self.state, self.last_error = "offline", ""
                return interval
            if ((bc.get("snippet") or {}).get("channelId") or target) != target:
                self.state, self.last_error = "config_error", "The active broadcast belongs to a different channel than the target. SavahBot did not attach."
                return 60.0
            self.chat_id, self.video_id, self.title = chat, bc.get("id", ""), (bc.get("snippet") or {}).get("title", "")
            self.video_channel_id = target
            self._page_token, self._first_poll, self.last_error = "", True, ""
            self._stream_started, self.state = time.time(), "live"
            self.hub.stream_state(True, self.title or "YouTube live stream")
            return 0.0

        # Someone else's channel: search is the documented way to find its live video, but it is expensive.
        day = self.quota.day()
        if day != self._detect_day:
            self._detect_day, self._detect_spent = day, await self.quota.store.quota_get(f"detect:{day}")   # kept in the database: a restart must not reset the cap
        cost = self.quota.cost("search")
        wait = float(self.cfg.get("youtube_target_detect_interval_seconds"))
        if self._detect_spent + cost > self.cfg.get("yt_daily_quota") * self.cfg.get("yt_detect_budget_fraction") or not self.quota.can_afford("search"):
            self.state = "search_paused"
            self.last_error = ("Searching for the stream is paused for today to protect the YouTube quota. "
                               "Set YOUTUBE_VIDEO_ID to the live video's ID or link to attach directly.")
            return 900.0
        self._detect_spent += cost
        await self.quota.store.quota_add(f"detect:{day}", cost)
        await self.quota.spend(cost)
        status, data = await self._api("GET", "/search", params={"part": "id", "type": "video", "eventType": "live", "channelId": target, "maxResults": 5})
        bad = self._detect_failure(status, data, wait)
        if bad is not None:
            return bad
        ids = [((i.get("id") or {}).get("videoId")) for i in (data.get("items") or [])] if isinstance(data, dict) else []
        ids = [i for i in ids if i]
        if not ids:
            self.state, self.last_error = "offline", ""
            return wait
        status, data = await self._videos(ids)
        bad = self._detect_failure(status, data, wait)
        if bad is not None:
            return bad
        for item in (data.get("items") or []):
            if (item.get("snippet") or {}).get("channelId") == target and (item.get("liveStreamingDetails") or {}).get("activeLiveChatId"):
                return self._attach(item)
        self.state, self.last_error = "offline", ""
        return wait

    async def _poll(self) -> float:
        interval = self.quota.read_interval(time.time() - self._stream_started)
        if interval is None:
            self.state = "quota_low"
            self.last_error = "Daily YouTube quota is nearly used up. Chat reading is paused until it resets."
            return 120.0
        await self.quota.spend(self.quota.cost("chat_list"))
        params = {"liveChatId": self.chat_id, "part": "snippet,authorDetails", "maxResults": self.cfg.get("youtube_max_results")}
        if self._page_token:
            params["pageToken"] = self._page_token
        status, data = await self._api("GET", "/liveChat/messages", params=params)
        self.last_poll = time.time()
        self.polls += 1
        if status == 200 and isinstance(data, dict):
            self._page_token = data.get("nextPageToken", self._page_token)
            backfill = self._first_poll
            self._first_poll = False
            self.state, self.last_error = "live", ""
            self._errors = 0
            self.perms["read"] = True
            ended = False
            for item in data.get("items", []):
                if (item.get("snippet") or {}).get("type") == "chatEndedEvent":
                    ended = True  # YouTube says this chat is over: stop here instead of waiting for an error on the next poll
                    continue
                msg = parse_item(item)
                if msg is None:
                    continue
                if backfill:
                    if not self.cfg.get("youtube_backfill_on_connect"):
                        continue
                    msg.backfill = True
                await self.hub.ingest(msg)
            if ended:
                self._detach()
                self.state = "offline"
                return 5.0
            api_wait = float(data.get("pollingIntervalMillis", 0)) / 1000.0
            return max(api_wait, interval)
        reason = _reason(data)
        if reason in ENDED_REASONS or status == 404:
            self._detach()
            self.state = "offline"
            return 5.0
        if status == 401:
            self.state, self.last_error = "error", self._auth_message(401, data)
            return 60.0
        if status == 403 and reason in PERMISSION_REASONS:
            self._detach()
            self.perms["read"] = False
            self.state = "no_permission"
            self.last_error = (f"YouTube will not let this account read that live chat ({reason}). If you are not the channel owner, ask them to "
                               "appoint the signed-in account as a moderator in YouTube Studio, or reconnect with the right Google account.")
            return float(self.cfg.get("youtube_permission_retry_seconds"))
        if reason in QUOTA_REASONS:
            await self.quota.mark_exhausted()
            self.state, self.last_error = "quota_low", "YouTube says the daily quota is used up. It resets at midnight Pacific Time."
            return 300.0
        if reason == "rateLimitExceeded":
            return max(interval * 2, 10.0)
        self.last_error = f"YouTube answered {status} ({reason or 'no detail'}) while reading chat."
        self.state = "error"
        return self._backoff()

    # ------------------------------------------------------------------ actions (the ChatSource interface)
    def _denial(self, key: str) -> str:
        """The refusal message while YouTube's "not permitted" answer for this kind of action is still fresh, else ''."""
        denied = self._denied.get(key)
        if denied and time.time() < denied[0]:
            return denied[1]
        self._denied.pop(key, None)
        return ""

    async def preflight(self, deletes: int, action: str) -> tuple[bool, str]:
        """Check the whole approval is allowed and affordable BEFORE doing any of it, so an action is all-or-nothing."""
        await self.quota.sync()
        blocked = self._identity_gate()
        if blocked:
            return False, blocked
        for needed, key in ((deletes > 0, "delete"), (action in ("timeout", "ban"), "ban")):
            msg = self._denial(key) if needed else ""
            if msg:
                return False, msg  # YouTube already refused this account for that; do not queue half an action
        need = deletes * self.quota.cost("chat_delete") + (self.quota.cost("ban") if action in ("timeout", "ban") else 0)
        if self.quota.remaining < need:
            return False, f"YouTube quota too low: this needs {need} units but only {self.quota.remaining} are left today."
        return True, ""

    async def _action(self, kind: str, method: str, path: str, *, params: dict | None = None, body: Any = None) -> tuple[bool, str]:
        """True only when YouTube itself confirmed it (200/204, or 404 for a message that is already gone)."""
        await self.quota.sync()
        if not self.chat_id:
            return False, "No live chat is attached right now."
        blocked = self._identity_gate()
        if blocked:
            return False, blocked  # the signed-in account is not confirmed to be the intended moderator: do nothing
        key = ACTION_PERM[kind]
        cooling = self._denial(key)
        if cooling:
            return False, cooling  # refused moments ago for lack of permission: no request, no quota
        if not self.quota.can_afford(kind):
            return False, "YouTube quota exhausted for today."
        await self.quota.spend(self.quota.cost(kind))
        try:
            status, data = await self._api(method, path, params=params, body=body)
        except RuntimeError as exc:
            return False, str(exc)
        if status in (200, 204):
            self.perms[key] = True
            return True, ""
        reason = _reason(data)
        if reason in QUOTA_REASONS:
            await self.quota.mark_exhausted()
            return False, "YouTube quota exhausted for today."
        if kind == "chat_delete" and status == 404:
            return True, ""  # already gone
        label = ACTION_LABEL.get(kind, kind)
        if status == 401:
            msg = self._auth_message(401, data)
        elif reason in PROTECTED_USER_REASONS:
            msg = f"YouTube will not allow this on that person ({reason}). They may be a moderator or the channel owner."
        elif reason in ENDED_REASONS:
            msg = "That live chat is no longer available (the stream may have ended)."
        elif status == 403 or reason in PERMISSION_REASONS:
            retry = float(self.cfg.get("youtube_permission_retry_seconds"))
            msg = (f"YouTube says this account is {DENIED_PHRASE} {label} in that chat ({reason or 403}). "
                   f"It must be the channel owner or a moderator appointed in YouTube Studio. Not trying that again for {max(1, round(retry / 60))} min.")
            self.perms[key] = False
            self._denied[key] = (time.time() + retry, msg)
        else:
            msg = f"YouTube refused ({reason or status})"
        self.last_action_error = msg
        return False, msg

    async def send(self, text: str) -> bool:
        ok, err = await self._action("chat_insert", "POST", "/liveChat/messages", params={"part": "snippet"}, body={
            "snippet": {"liveChatId": self.chat_id, "type": "textMessageEvent", "textMessageDetails": {"messageText": text}}})
        if not ok:
            self.last_error = err
        return ok

    async def delete(self, msg_id: str) -> tuple[bool, str]:
        return await self._action("chat_delete", "DELETE", "/liveChat/messages", params={"id": msg_id})

    async def timeout(self, author_id: str, seconds: int) -> tuple[bool, str]:
        return await self._action("ban", "POST", "/liveChat/bans", params={"part": "snippet"}, body={"snippet": {
            "liveChatId": self.chat_id, "type": "temporary", "banDurationSeconds": int(seconds), "bannedUserDetails": {"channelId": author_id}}})

    async def ban(self, author_id: str) -> tuple[bool, str]:
        return await self._action("ban", "POST", "/liveChat/bans", params={"part": "snippet"}, body={"snippet": {
            "liveChatId": self.chat_id, "type": "permanent", "bannedUserDetails": {"channelId": author_id}}})

    # ------------------------------------------------------------------ sign-in: check WHO signed in before keeping the login
    async def accept_login(self, pending: PendingLogin) -> tuple[bool, str]:
        """Decide what to do with a fresh Google sign-in. Returns (kept, message for the dashboard).

        The new tokens are only saved after Google has said which account they belong to. A wrong account is dropped and the
        previous connection (if there was one) is left exactly as it was, so a mistaken sign-in can neither stay connected as the
        intended moderator nor destroy a working connection."""
        expected = self._expected_account()
        had_login = await self.auth.connected()
        kept_note = " Your previous connection was left unchanged." if had_login else ""
        acct: dict[str, str] | None = None
        status: int | str = 0
        try:
            if self.quota.can_afford("channel_list"):
                await self.quota.spend(self.quota.cost("channel_list"))
            url = self.cfg.get("youtube_api_base").rstrip("/") + "/channels"
            status, data = await request_json("GET", url, params={"part": "id,snippet", "mine": "true"},
                                              headers={"Authorization": f"Bearer {pending.access}"}, timeout=15)
            if status == 200 and isinstance(data, dict):
                items = data.get("items") or []
                sn = (items[0].get("snippet") or {}) if items else {}
                acct = {"channel_id": items[0].get("id", "") if items else "", "title": sn.get("title", ""), "handle": sn.get("customUrl", "")}
        except NetworkError as exc:
            status = f"network error: {exc}"
        if acct is None and expected:
            return False, (f"Could not confirm which Google account just signed in (YouTube answered {status}), and YOUTUBE_MODERATOR_ACCOUNT "
                           f"is set to {expected}, so this sign-in was NOT saved.{kept_note} Try again in a minute.")
        if acct is not None:
            mismatch = self._mismatch_for(acct)
            if mismatch:
                return False, (f"You signed in as {self._describe(acct)}, but YOUTUBE_MODERATOR_ACCOUNT expects {expected}. "
                               f"That sign-in was NOT saved.{kept_note} Sign in again with the right Google account.")
        previous = self.account
        await self.auth.commit_login(pending)
        self._identity_tried = time.time()
        if acct is None:
            self.forget_identity()
            return True, ("YouTube is connected, but SavahBot could not look up which account it is "
                          f"(YouTube answered {status}). No YOUTUBE_MODERATOR_ACCOUNT is set, so nothing was checked.")
        if previous is None or previous.get("channel_id") != acct["channel_id"]:
            self.forget_identity()  # a different account: drop the old stream, permissions and refusals
        self.account = acct
        note = ""
        if previous and previous.get("channel_id") != acct["channel_id"]:
            note = f" It replaces {self._describe(previous)}; any stream that was attached was released and will be found again."
        return True, f"YouTube is connected as {self._describe(acct)}. That account's permissions are what SavahBot will use.{note}"

    # ------------------------------------------------------------------ Verify access
    async def diagnose(self) -> dict[str, Any]:
        """Ask the real YouTube API what this account can do for the target channel. Nothing is moderated or changed.

        Reading chat is probed for real. Deleting and banning cannot be probed (YouTube has no dry run), so they are reported as
        unverified until YouTube has answered a real action. It never searches for a stream (that costs 100 units): it uses the
        attached stream, or the pinned YOUTUBE_VIDEO_ID."""
        saved = (self.state, self.last_error)
        checks: list[dict[str, Any]] = []

        def add(ok: bool | None, label: str, detail: str) -> None:
            checks.append({"ok": ok, "label": label, "detail": detail})

        def result() -> dict[str, Any]:
            return {"ok": all(c["ok"] is not False for c in checks), "checks": checks}

        try:
            if not await self.auth.connected():
                add(False, "Google account", "Not connected. Press Connect on the Setup page and sign in with the moderator account.")
                return result()
            fresh, status = await self._fetch_account()
            if fresh is None:
                add(False, "Signed-in account", f"Google would not say which account is signed in (YouTube answered {status}).")
            elif not fresh.get("channel_id"):
                add(False, "Signed-in account", "This Google account has no YouTube channel, so it cannot moderate.")
            else:
                add(True, "Signed-in account", f"{self._describe(fresh)} (reported by Google).")
            if fresh is not None:
                self.account = fresh
            gate = self._identity_gate()
            if self._expected_account():
                add(not gate, "Expected account", gate or f"Matches YOUTUBE_MODERATOR_ACCOUNT ({self._expected_account()}).")
            problem = await self._resolve_target()
            add(not problem, "Target channel", problem or f"Moderating the live chat of {self.target['channel_id']}.")  # type: ignore[index]
            if problem or gate or fresh is None or not fresh.get("channel_id"):
                return result()
            target = self.target["channel_id"]  # type: ignore[index]
            own = fresh["channel_id"] == target
            add(True, "Role", "The signed-in account owns the target channel." if own else
                "The signed-in account is not the owner: it acts as a moderator, which the owner must have appointed in YouTube Studio.")
            chat, label = self.chat_id, "the attached stream"
            if not chat:
                video = parse_video_id(self.cfg.get("youtube_video_id"))
                if not video:
                    add(None, "Livestream", "No stream is attached and no YOUTUBE_VIDEO_ID is pinned, so chat reading cannot be tested now. "
                        "Verify never searches (it costs 100 quota units). Run it again while live, or pin the video.")
                else:
                    status, data = await self._videos([video])
                    vid = ((data.get("items") or [None])[0]) if status == 200 and isinstance(data, dict) else None
                    if vid is None:
                        add(False, "Livestream", f"YouTube did not return video {video} (answer {status}).")
                    elif (vid.get("snippet") or {}).get("channelId") != target:
                        add(False, "Livestream", f"Video {video} belongs to another channel than the target. It would be refused.")
                    elif not (vid.get("liveStreamingDetails") or {}).get("activeLiveChatId"):
                        add(None, "Livestream", f"Video {video} is not live right now.")
                    else:
                        chat, label = vid["liveStreamingDetails"]["activeLiveChatId"], f"video {video}"
            if chat:
                add(True, "Livestream", f"Using {label}.")
                if self.quota.can_afford("chat_list"):
                    await self.quota.spend(self.quota.cost("chat_list"))
                    status, data = await self._api("GET", "/liveChat/messages", params={"liveChatId": chat, "part": "snippet", "maxResults": 200})
                    reason = _reason(data)
                    if status == 200:
                        self.perms["read"] = True
                        add(True, "Read chat", "YouTube let this account read the chat.")
                    elif status == 403 and reason in PERMISSION_REASONS:
                        self.perms["read"] = False
                        add(False, "Read chat", f"YouTube refused ({reason}). This account cannot read that chat.")
                    else:
                        add(False, "Read chat", f"YouTube answered {status} ({reason or 'no detail'}).")
                else:
                    add(None, "Read chat", "Not enough quota left to test it today.")
            for key, text in (("delete", "Delete messages"), ("ban", "Ban / time out")):
                known = self.perms[key]
                add(known, text, "Confirmed by a real action." if known else "Refused by YouTube on the last attempt." if known is False else
                    "Unverified: YouTube has no dry run. It requires the owner or an appointed moderator; the first real action will show.")
            return result()
        except RuntimeError as exc:
            add(False, "YouTube", str(exc))
            return result()
        finally:
            self.state, self.last_error = saved
