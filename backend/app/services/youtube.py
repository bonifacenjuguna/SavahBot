"""YouTube live chat: OAuth, a quota governor, livestream discovery, chat polling and moderation actions.

Two identities are kept strictly apart:

  * the AUTHENTICATED ACCOUNT: the Google/YouTube account whose OAuth token SavahBot holds (the owner, or a
    moderator appointed by the owner). Its identity is read from Google (channels.list mine=true), never from a setting.
  * the TARGET CHANNEL (YOUTUBE_TARGET_CHANNEL_ID): the channel whose livestream chat is monitored and moderated.

Every request is made with the account's token; the target channel only decides WHICH stream is attached. SavahBot
never falls back to the account's own channel when the target is missing or unreachable.

The YouTube Data API gives every project 10,000 quota units a day. Reading chat is the biggest recurring
cost, so the governor spreads a share of the daily budget (YT_READ_BUDGET_FRACTION) across the expected
stream length (YOUTUBE_EXPECTED_STREAM_HOURS) and keeps the rest for actions (deletes cost 20, bans 200).
All costs are configurable because Google changes them; verify them in the YouTube docs.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import time
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from ..http import NetworkError, request_json
from ..models import ChatMessage

logger = logging.getLogger("savahbot.youtube")
CALLBACK_PATH = "/api/youtube/oauth/callback"
CHANNEL_ID_RE = re.compile(r"^UC[0-9A-Za-z_-]{22}$")
PERMISSION_REASONS = frozenset({"forbidden", "insufficientPermissions"})
QUOTA_REASONS = frozenset({"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"})
ENDED_REASONS = frozenset({"liveChatEnded", "liveChatNotFound", "liveChatDisabled"})


class AuthError(RuntimeError):
    """Google refused or revoked the login. Only reconnecting the account fixes it."""


# ---------------------------------------------------------------------------------------------
class QuotaTracker:
    def __init__(self, cfg: Any, store: Any, now_fn: Callable[[], float] = time.time) -> None:
        self.cfg = cfg
        self.store = store
        self.now_fn = now_fn
        self._day = ""
        self._used = 0

    def day(self) -> str:
        return datetime.fromtimestamp(self.now_fn(), ZoneInfo(self.cfg.get("yt_quota_reset_tz"))).strftime("%Y-%m-%d")

    async def sync(self) -> None:
        d = self.day()
        if d != self._day:
            self._day = d
            self._used = await self.store.quota_get(d)

    async def spend(self, units: int) -> None:
        await self.sync()
        self._used += units
        await self.store.quota_add(self._day, units)

    async def mark_exhausted(self) -> None:
        await self.sync()
        missing = self.cfg.get("yt_daily_quota") - self._used
        if missing > 0:
            self._used += missing
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
                "day": self._day or self.day(), "reset_tz": self.cfg.get("yt_quota_reset_tz")}


# ---------------------------------------------------------------------------------------------
class GoogleAuth:
    def __init__(self, cfg: Any, db: Any, now_fn: Callable[[], float] = time.time) -> None:
        self.cfg = cfg
        self.db = db
        self.now_fn = now_fn
        self._access = ""
        self._expires = 0.0
        self._states: dict[str, float] = {}
        self.last_error = ""
        self.generation = 0  # bumped whenever the connected account may have changed (connect / disconnect)

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

    async def _forget_account(self) -> None:
        self.generation += 1
        await self.db.kv_delete("youtube_account")

    async def exchange_code(self, code: str) -> None:
        status, data = await request_json("POST", self.cfg.get("google_oauth_token_url"), form={
            "code": code, "client_id": self.cfg.get("google_client_id"), "client_secret": self.cfg.get("google_client_secret"),
            "redirect_uri": self.redirect_uri(), "grant_type": "authorization_code"})
        if status != 200 or not isinstance(data, dict) or not data.get("access_token"):
            raise RuntimeError(f"Google rejected the authorisation code ({(data or {}).get('error_description') or (data or {}).get('error') or status})")
        if data.get("refresh_token"):
            await self.db.kv_set("youtube_refresh_token", data["refresh_token"])
        elif not await self.refresh_token():
            raise RuntimeError("Google did not return a refresh token. Remove SavahBot from your Google account's third-party access and connect again.")
        self._access, self._expires = data["access_token"], self.now_fn() + float(data.get("expires_in", 3600)) - 60
        self.last_error = ""
        await self._forget_account()  # a different Google account may have signed in: identify it again

    async def access_token(self, force: bool = False) -> str:
        if not force and self._access and self.now_fn() < self._expires:
            return self._access
        refresh = await self.refresh_token()
        if not refresh or not self.cfg.get("google_client_id"):
            raise AuthError("YouTube is not connected. Press Connect on the Setup page and sign in with the moderator account.")
        try:
            status, data = await request_json("POST", self.cfg.get("google_oauth_token_url"), form={
                "client_id": self.cfg.get("google_client_id"), "client_secret": self.cfg.get("google_client_secret"),
                "refresh_token": refresh, "grant_type": "refresh_token"})
        except NetworkError as exc:
            raise RuntimeError(f"Could not reach Google ({exc})") from None
        if status != 200 or not isinstance(data, dict) or not data.get("access_token"):
            body = data if isinstance(data, dict) else {}
            reason = body.get("error_description") or body.get("error") or status
            self._access, self._expires = "", 0.0
            if status in (400, 401):  # invalid_grant: revoked, expired (test-mode apps expire after 7 days) or password changed
                self.last_error = (f"Google refused to refresh the login ({reason}). Reconnect YouTube from the Setup page, "
                                   "signing in with the moderator account.")
                raise AuthError(self.last_error)
            self.last_error = f"Google could not refresh the login right now ({reason}). Will retry."
            raise RuntimeError(self.last_error)
        self._access, self._expires = data["access_token"], self.now_fn() + float(data.get("expires_in", 3600)) - 60
        self.last_error = ""
        return self._access

    async def disconnect(self) -> None:
        await self.db.kv_delete("youtube_refresh_token")
        self._access, self._expires = "", 0.0
        await self._forget_account()


# ---------------------------------------------------------------------------------------------
def _reason(data: Any) -> str:
    try:
        err = data["error"]
        return (err.get("errors") or [{}])[0].get("reason") or err.get("status") or err.get("message", "")
    except (TypeError, KeyError, AttributeError, IndexError):
        return ""


def _norm(value: str) -> str:
    return (value or "").strip().lstrip("@").lower()


def account_matches(expected: str, account: dict[str, str]) -> bool:
    """Does the account Google reports match what the owner said to expect? Blank expectation always matches.

    Accepts a channel ID (UC...), an @handle or the channel name. This is only a safety check against connecting the
    wrong Google account; it never grants anything, and the identity itself always comes from Google."""
    want = _norm(expected)
    if not want:
        return True
    return want in {_norm(account.get("channel_id", "")), _norm(account.get("handle", "")), _norm(account.get("title", ""))}


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


ACTION_VERBS = {"chat_insert": "post messages", "chat_delete": "delete messages", "ban": "ban or time out users"}
ACTION_PERM = {"chat_insert": "send", "chat_delete": "delete", "ban": "ban"}


class YouTubeSource:
    name = "youtube"

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
        # identity bookkeeping: WHO is signed in (account) is kept apart from WHICH channel is moderated (target)
        self.account: dict[str, str] = {}
        self._account_gen = -1
        self.target_title = ""
        self.mode = "unknown"            # "owner" (account owns the target) or "moderator" (it does not)
        self.problem = ""                # "", config, account, target_mismatch, video, permission, auth
        self.perms: dict[str, bool | None] = {"read": None, "delete": None, "ban": None, "send": None}  # only ever set by real YouTube answers
        self._denied: dict[str, tuple[float, str]] = {}
        self._errors = 0
        self._last_search = 0.0
        self._last_ids: tuple[str, ...] = ()
        self._upcoming_seen = True

    # ------------------------------------------------------------------ identities
    def target_channel_id(self) -> str:
        return (self.cfg.get("youtube_target_channel_id") or self.cfg.get("youtube_channel_id") or "").strip()

    def account_label(self) -> str:
        return self.account.get("title") or self.account.get("channel_id") or "the connected account"

    async def account_info(self) -> dict[str, str]:
        """The authenticated account as last reported by Google (remembered across restarts)."""
        if self.account:
            return dict(self.account)
        raw = await self.auth.db.kv_get("youtube_account")
        try:
            return dict(json.loads(raw)) if raw else {}
        except (ValueError, TypeError):
            return {}

    def _config_problem(self, target: str) -> str:
        if not target:
            hint = f" The connected account's own channel is {self.account['channel_id']}: use that ONLY if it is the channel you want to moderate." if self.account else ""
            return ("No target channel is configured. Set YOUTUBE_TARGET_CHANNEL_ID to the channel ID (starts with UC) of the channel whose live chat "
                    "you moderate. SavahBot never guesses it and never falls back to the connected account's own channel." + hint)
        if not CHANNEL_ID_RE.match(target):
            return ("YOUTUBE_TARGET_CHANNEL_ID must be a channel ID: 24 characters starting with UC. A @handle or a channel name will not work. "
                    "Open the channel > About > Share channel > Copy channel ID.")
        return ""

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

    def status(self) -> dict[str, Any]:
        target = self.target_channel_id()
        return {"state": self.state, "connected": self._connected_cache, "chat_attached": bool(self.chat_id), "video_id": self.video_id,
                "title": self.title, "last_error": self.last_error or self.auth.last_error, "last_poll": self.last_poll or None,
                "polls": self.polls, "quota": self.quota.status(), "redirect_uri": self.auth.redirect_uri(),
                "mode": self.mode, "problem": self.problem, "permissions": dict(self.perms),
                "account": {"channel_id": self.account.get("channel_id", ""), "title": self.account.get("title", ""), "handle": self.account.get("handle", "")},
                "expected_account": self.cfg.get("youtube_moderator_account") or "",
                "target": {"channel_id": target, "title": self.target_title, "configured": bool(target),
                          "deprecated_variable": bool(target and not self.cfg.get("youtube_target_channel_id"))}}

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
        if status == 401:
            raise AuthError("YouTube rejected the login even after a refresh. Reconnect YouTube from the Setup page, signing in with the moderator account.")
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
            except AuthError as exc:
                self.last_error, self.problem, self.state = str(exc), "auth", "auth_error"
                wait = 120.0
            except RuntimeError as exc:
                self.last_error = str(exc)
                self.state = "error"
                wait = self._backoff()
            except Exception:
                logger.exception("YouTube loop error")
                self.last_error = "Unexpected error, see server logs"
                self.state = "error"
                wait = self._backoff()

    def _backoff(self) -> float:
        self._errors += 1
        return min(300.0, 30.0 * 2 ** (self._errors - 1))

    async def _step(self) -> float:
        await self.quota.sync()
        self._connected_cache = await self.auth.connected()
        if not self._connected_cache:
            self.state = "not_connected"
            return 5.0
        if not self.chat_id:
            return await self._detect()
        return await self._poll()

    # ------------------------------------------------------------------ discovery
    async def _fail(self, status: int, data: Any, what: str) -> float:
        """Turn an unexpected YouTube answer into a state + message, and return how long to wait."""
        reason = _reason(data)
        if status == 403 and reason in QUOTA_REASONS:
            await self.quota.mark_exhausted()
            self.state, self.last_error = "quota_low", "YouTube says the daily quota is used up. It resets at midnight Pacific Time."
            return 300.0
        if status in (401, 403):
            self.state, self.problem = "error", "permission"
            self.last_error = (f"YouTube refused {what} ({reason or status}). Check that the YouTube Data API v3 is enabled in your Google Cloud "
                               "project and that the connected account is allowed to see this channel.")
            return 60.0
        self.last_error = f"YouTube answered {status} during {what}."
        self.state = "error"
        return self._backoff()

    async def _videos(self, ids: str) -> tuple[int, Any]:
        await self.quota.spend(self.quota.cost("video_list"))
        return await self._api("GET", "/videos", params={"part": "snippet,liveStreamingDetails", "id": ids})

    async def _ensure_account(self) -> float | None:
        """Learn who the OAuth token belongs to (from Google, never from a setting). None = fine, else seconds to wait."""
        if self._account_gen != self.auth.generation:
            self.account, self._account_gen = {}, self.auth.generation
        if not self.account:
            if not self.quota.can_afford("channel_list"):
                self.state, self.last_error = "quota_low", "Not enough YouTube quota left to identify the connected account."
                return 300.0
            await self.quota.spend(self.quota.cost("channel_list"))
            status, data = await self._api("GET", "/channels", params={"part": "id,snippet", "mine": "true"})
            if status != 200 or not isinstance(data, dict):
                return await self._fail(status, data, "the account lookup")
            items = data.get("items") or []
            if not items:
                self.state, self.problem = "error", "account"
                self.last_error = "The connected Google account has no YouTube channel, so it cannot be a moderator. Reconnect with the right account."
                return 60.0
            sn = items[0].get("snippet") or {}
            self.account = {"channel_id": items[0].get("id", ""), "title": sn.get("title", ""), "handle": sn.get("customUrl", "")}
            try:
                await self.auth.db.kv_set("youtube_account", json.dumps(self.account))
            except Exception:
                logger.warning("Could not remember the connected account")
        expected = self.cfg.get("youtube_moderator_account")
        if not account_matches(expected, self.account):
            self.state, self.problem = "wrong_account", "account"
            self.last_error = (f"The connected Google account is {self.account_label()} ({self.account.get('channel_id')}), but YOUTUBE_MODERATOR_ACCOUNT "
                               f"expects {expected}. Reconnect YouTube signing in with the right account, or correct that setting.")
            return 60.0
        return None

    def _from_video(self, item: dict[str, Any], target: str) -> dict[str, str] | float | None:
        """Accept a video only if it belongs to the target channel and has a live chat. float = rejected (wait)."""
        sn, lsd = item.get("snippet") or {}, item.get("liveStreamingDetails") or {}
        channel = sn.get("channelId", "")
        if channel != target:
            self.state, self.problem = "target_mismatch", "target_mismatch"
            self.last_error = (f"Video {item.get('id', '?')} belongs to channel {channel or 'unknown'} ({sn.get('channelTitle', 'unknown name')}), not the target channel "
                               f"{target}. Refusing to attach. Fix YOUTUBE_VIDEO_ID or YOUTUBE_TARGET_CHANNEL_ID.")
            return 60.0
        chat = lsd.get("activeLiveChatId")
        if not chat or lsd.get("actualEndTime"):
            return None
        return {"chat": chat, "id": item.get("id", ""), "title": sn.get("title", ""), "channel_title": sn.get("channelTitle", "")}

    async def _lookup_video(self, video: str, target: str) -> dict[str, str] | float | None:
        if not self.quota.can_afford("video_list"):
            self.state = "quota_low"
            return 300.0
        status, data = await self._videos(video)
        if status != 200 or not isinstance(data, dict):
            return await self._fail(status, data, "the video lookup")
        item = (data.get("items") or [None])[0]
        if item is None:
            self.state, self.problem = "error", "video"
            self.last_error = f"YouTube found no video {video}. The ID may be wrong or the video private. SavahBot will not pick a different stream."
            return 60.0
        return self._from_video(item, target)

    async def _discover(self, target: str) -> dict[str, str] | float | None:
        if self.mode == "owner":
            return await self._discover_own(target)
        return await self._discover_public(target)

    async def _discover_own(self, target: str) -> dict[str, str] | float | None:
        """The account owns the target channel: its own active broadcasts (this also finds unlisted and private streams)."""
        if not self.quota.can_afford("broadcast_list"):
            self.state = "quota_low"
            return 300.0
        await self.quota.spend(self.quota.cost("broadcast_list"))
        status, data = await self._api("GET", "/liveBroadcasts", params={"part": "snippet,status", "broadcastStatus": "active", "broadcastType": "all"})
        if status != 200 or not isinstance(data, dict):
            return await self._fail(status, data, "the broadcast lookup")
        for item in data.get("items") or []:
            sn = item.get("snippet") or {}
            if sn.get("liveChatId") and sn.get("channelId", target) == target:
                return {"chat": sn["liveChatId"], "id": item.get("id", ""), "title": sn.get("title", ""), "channel_title": self.account.get("title", "")}
        return None

    async def _discover_public(self, target: str) -> dict[str, str] | float | None:
        """The account is only a moderator: liveBroadcasts.list is owner-only, so read the target channel's PUBLIC data instead.

        Recent uploads (playlistItems, 1 unit) -> videos.list (1 unit) tells us which one is live and gives its activeLiveChatId.
        Unlisted or private streams are invisible this way: pin them with YOUTUBE_VIDEO_ID. Search (100 units) is an opt-in extra."""
        if self.quota.remaining < self.quota.cost("playlist_list") + self.quota.cost("video_list"):
            self.state = "quota_low"
            return 300.0
        await self.quota.spend(self.quota.cost("playlist_list"))
        status, data = await self._api("GET", "/playlistItems", params={"part": "contentDetails", "playlistId": "UU" + target[2:], "maxResults": 5})
        if status == 404:
            self.state, self.problem = "error", "config"
            self.last_error = f"YouTube has no public uploads list for channel {target}. Check YOUTUBE_TARGET_CHANNEL_ID."
            return 60.0
        if status != 200 or not isinstance(data, dict):
            return await self._fail(status, data, "the channel lookup")
        ids = tuple(((it.get("contentDetails") or {}).get("videoId", "") for it in data.get("items") or []))
        ids = tuple(i for i in ids if i)
        if ids and (ids != self._last_ids or self._upcoming_seen):
            status, data = await self._videos(",".join(ids))
            if status != 200 or not isinstance(data, dict):
                return await self._fail(status, data, "the video lookup")
            items = data.get("items") or []
            self._last_ids = ids
            self._upcoming_seen = any((i.get("snippet") or {}).get("liveBroadcastContent") in ("live", "upcoming") for i in items)
            for item in items:
                lsd = item.get("liveStreamingDetails") or {}
                if (item.get("snippet") or {}).get("liveBroadcastContent") == "live" and lsd.get("activeLiveChatId") and not lsd.get("actualEndTime"):
                    return self._from_video(item, target)
        if self.cfg.get("youtube_discovery_use_search") and time.time() - self._last_search >= self.cfg.get("youtube_search_interval_seconds") \
                and self.quota.can_afford("search_list"):
            self._last_search = time.time()
            await self.quota.spend(self.quota.cost("search_list"))
            status, data = await self._api("GET", "/search", params={"part": "snippet", "type": "video", "eventType": "live", "channelId": target, "maxResults": 1})
            if status != 200 or not isinstance(data, dict):
                return await self._fail(status, data, "the live search")
            vid = (((data.get("items") or [{}])[0]).get("id") or {}).get("videoId")
            if vid:
                return await self._lookup_video(vid, target)
        return None

    async def _find(self, target: str) -> dict[str, str] | float | None:
        video = (self.cfg.get("youtube_video_id") or "").strip()
        if video:
            return await self._lookup_video(video, target)
        if self.cfg.get("youtube_auto_detect_live"):
            return await self._discover(target)
        return None

    async def _detect(self) -> float:
        interval = float(self.cfg.get("youtube_detect_interval_seconds"))
        target = self.target_channel_id()
        bad = self._config_problem(target)
        if bad:
            wait = await self._ensure_account()  # still learn (and show) who is connected, to make the hint useful
            if wait is not None and self.problem == "account":
                return wait
            self.state, self.problem, self.last_error = "config_error", "config", self._config_problem(target)
            return 60.0
        wait = await self._ensure_account()
        if wait is not None:
            return wait
        self.mode = "owner" if self.account.get("channel_id") == target else "moderator"
        self.problem = ""
        found = await self._find(target)
        if isinstance(found, float):
            return found
        if found is None:
            self.state, self.last_error = "offline", ""
            self._errors = 0
            return interval
        self.chat_id, self.video_id, self.title = found["chat"], found["id"], found["title"]
        self.target_title = found.get("channel_title", "")
        self._page_token, self._first_poll, self.last_error = "", True, ""
        self._stream_started = time.time()
        self._errors = 0
        self._denied.clear()
        self.perms["read"] = None
        self.state = "live"
        self.hub.stream_state(True, self.title or "YouTube live stream")
        return 0.0

    # ------------------------------------------------------------------ polling
    def _chat_over(self) -> float:
        self.chat_id, self._page_token, self.title = "", "", ""
        self._last_ids, self._upcoming_seen = (), True
        self.state = "offline"
        self.hub.stream_state(False)
        return 5.0

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
            self._errors = 0
            self.perms["read"] = True
            self.state, self.last_error = "live", ""
            ended = False
            for item in data.get("items", []):
                if (item.get("snippet") or {}).get("type") == "chatEndedEvent":
                    ended = True
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
                return self._chat_over()
            api_wait = float(data.get("pollingIntervalMillis", 0)) / 1000.0
            return max(api_wait, interval)
        reason = _reason(data)
        if reason in ENDED_REASONS or status == 404:
            return self._chat_over()
        if reason in QUOTA_REASONS and reason != "rateLimitExceeded":
            await self.quota.mark_exhausted()
            self.state, self.last_error = "quota_low", "YouTube says the daily quota is used up. It resets at midnight Pacific Time."
            return 300.0
        if reason == "rateLimitExceeded":
            return max(interval * 2, 10.0)
        if status == 403 and reason in PERMISSION_REASONS:
            # The account may not read this chat. Say so plainly, stop reading it, and look again later (never spin on a no).
            retry = float(self.cfg.get("youtube_permission_retry_seconds"))
            self.perms["read"] = False
            self.problem, self.state = "permission", "no_permission"
            self.last_error = (f"YouTube refused to let {self.account_label()} read the live chat of {self.target_channel_id()} ({reason}). "
                               f"Nothing is being moderated. Check that the account can see that chat; trying again in {int(retry // 60) or 1} min.")
            self.chat_id, self._page_token = "", ""
            self.hub.stream_state(False)
            return retry
        self.last_error = f"YouTube answered {status} ({reason or 'no detail'}) while reading chat."
        self.state = "error"
        return self._backoff()

    # ------------------------------------------------------------------ actions (the ChatSource interface)
    def _denial(self, key: str) -> str:
        denied = self._denied.get(key)
        return denied[1] if denied and time.time() < denied[0] else ""

    async def preflight(self, deletes: int, action: str) -> tuple[bool, str]:
        """Check the whole approval is affordable (and not known to be forbidden) BEFORE doing any of it, so an action is all-or-nothing."""
        await self.quota.sync()
        for needed, key in ((deletes > 0, "delete"), (action in ("timeout", "ban"), "ban")):
            msg = self._denial(key) if needed else ""
            if msg:
                return False, msg
        need = deletes * self.quota.cost("chat_delete") + (self.quota.cost("ban") if action in ("timeout", "ban") else 0)
        if self.quota.remaining < need:
            return False, f"YouTube quota too low: this needs {need} units but only {self.quota.remaining} are left today."
        return True, ""

    async def _action(self, kind: str, method: str, path: str, *, params: dict | None = None, body: Any = None) -> tuple[bool, str]:
        """True only when YouTube itself confirmed the action (HTTP 200/204, or 404 for a message that is already gone)."""
        await self.quota.sync()
        if not self.chat_id:
            return False, "No live chat is attached right now."
        key = ACTION_PERM[kind]
        blocked = self._denial(key)
        if blocked:
            return False, blocked  # YouTube already said no for lack of permission: do not hammer it, and spend nothing
        if not self.quota.can_afford(kind):
            return False, "YouTube quota exhausted for today."
        await self.quota.spend(self.quota.cost(kind))
        try:
            status, data = await self._api(method, path, params=params, body=body)
        except RuntimeError as exc:  # includes AuthError: the message already says how to reconnect
            return False, str(exc)
        if status in (200, 204):
            self.perms[key] = True
            return True, ""
        reason = _reason(data)
        if reason in QUOTA_REASONS - {"rateLimitExceeded"}:
            await self.quota.mark_exhausted()
            return False, "YouTube quota exhausted for today."
        if kind == "chat_delete" and status == 404:
            return True, ""  # YouTube says the message no longer exists: the goal (it is gone) holds
        if reason == "liveChatBanInsertionNotAllowed":
            return False, "YouTube does not allow banning the chat owner or another moderator."
        if reason == "modificationNotAllowed":
            return False, "YouTube will not delete that message (it may belong to a moderator or be protected)."
        if status == 403 and reason in PERMISSION_REASONS:
            retry = float(self.cfg.get("youtube_permission_retry_seconds"))
            msg = (f"YouTube refused: {self.account_label()} is not allowed to {ACTION_VERBS[kind]} in this chat ({reason}). "
                   f"The account must be appointed as a moderator of {self.target_channel_id()}. Not retrying for {int(retry // 60) or 1} min.")
            self.perms[key] = False
            self._denied[key] = (time.time() + retry, msg)
            self.last_error = msg
            return False, msg
        if reason in ENDED_REASONS or status == 404:
            return False, "That live chat is no longer available (the stream may have ended)."
        if reason in ("liveChatUserNotFound", "invalidChannelId"):
            return False, "YouTube cannot find that user in the chat any more."
        return False, f"YouTube refused ({reason or status})"

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

    async def identify(self) -> tuple[str, str]:
        """Ask Google who is connected (used right after sign-in). Returns ("ok" | "rejected" | "unknown", message)."""
        saved = (self.state, self.last_error, self.problem)
        try:
            wait = await self._ensure_account()
            if wait is None:
                return "ok", ""
            return ("rejected" if self.problem == "account" else "unknown"), self.last_error
        except RuntimeError as exc:
            return "unknown", str(exc)
        finally:
            self.state, self.last_error, self.problem = saved

    # ------------------------------------------------------------------ on-demand access check
    async def diagnose(self) -> dict[str, Any]:
        """Check, against the real YouTube API, what the connected account can actually do for the target channel.

        Reading is probed for real. Deleting and banning cannot be probed (YouTube has no dry run), so they are reported as
        unverified until a real action has been answered by YouTube."""
        saved = (self.state, self.last_error, self.problem, self.mode)
        checks: list[dict[str, Any]] = []

        def add(ok: bool | None, label: str, detail: str) -> None:
            checks.append({"ok": ok, "label": label, "detail": detail})

        try:
            if not await self.auth.connected():
                add(False, "Google account", "Not connected. Press Connect on the Setup page and sign in with the moderator account.")
                return {"ok": False, "checks": checks}
            target = self.target_channel_id()
            bad = self._config_problem(target)
            add(not bad, "Target channel", bad or f"Target channel is {target}.")
            wait = await self._ensure_account()
            if self.account:
                add(wait is None, "Connected account", f"{self.account_label()} ({self.account.get('channel_id')}) as reported by Google."
                    + ("" if wait is None else " " + self.last_error))
            else:
                add(False, "Connected account", self.last_error or "Could not identify the connected account.")
            if bad or wait is not None:
                return {"ok": False, "checks": checks}
            self.mode = "owner" if self.account.get("channel_id") == target else "moderator"
            add(True, "Role", "The account owns the target channel." if self.mode == "owner" else
                "The account is not the target channel's owner: it acts as a moderator (YouTube must have appointed it).")
            found = await self._find(target)
            if isinstance(found, float):
                add(False, "Livestream", self.last_error)
                return {"ok": False, "checks": checks}
            if found is None:
                add(None, "Livestream", "No live stream found right now. Start one (or pin YOUTUBE_VIDEO_ID) and check again.")
                return {"ok": True, "checks": checks}
            add(True, "Livestream", f"Found \"{found['title']}\" on channel {target}; it has a live chat.")
            await self.quota.spend(self.quota.cost("chat_list"))
            status, data = await self._api("GET", "/liveChat/messages", params={"liveChatId": found["chat"], "part": "snippet", "maxResults": 200})
            reason = _reason(data)
            if status == 200:
                self.perms["read"] = True
                add(True, "Read chat", "YouTube let the account read this chat.")
            elif status == 403 and reason in PERMISSION_REASONS:
                self.perms["read"] = False
                add(False, "Read chat", f"YouTube refused ({reason}). The account cannot read this chat.")
            else:
                add(False, "Read chat", f"YouTube answered {status} ({reason or 'no detail'}).")
            for key, label in (("delete", "Delete messages"), ("ban", "Ban / time out")):
                known = self.perms[key]
                add(known, label, "Confirmed by a real action." if known else "Refused by YouTube on the last attempt." if known is False else
                    "Not testable: YouTube has no dry run. Documented requirement: the account must be the channel owner or an appointed moderator. "
                    "The first real action will confirm it.")
            return {"ok": all(c["ok"] is not False for c in checks), "checks": checks}
        finally:
            self.state, self.last_error, self.problem, self.mode = saved
