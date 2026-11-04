"""YouTube live chat: OAuth, a quota governor, live-broadcast detection, chat polling and moderation actions.

The YouTube Data API gives every project 10,000 quota units a day. Reading chat is the biggest recurring
cost, so the governor spreads a share of the daily budget (YT_READ_BUDGET_FRACTION) across the expected
stream length (YOUTUBE_EXPECTED_STREAM_HOURS) and keeps the rest for actions (deletes cost 20, bans 200).
All costs are configurable because Google changes them; verify them in the YouTube docs.
"""
from __future__ import annotations

import asyncio
import logging
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

    async def access_token(self, force: bool = False) -> str:
        if not force and self._access and self.now_fn() < self._expires:
            return self._access
        refresh = await self.refresh_token()
        if not refresh or not self.cfg.get("google_client_id"):
            raise RuntimeError("YouTube is not connected")
        try:
            status, data = await request_json("POST", self.cfg.get("google_oauth_token_url"), form={
                "client_id": self.cfg.get("google_client_id"), "client_secret": self.cfg.get("google_client_secret"),
                "refresh_token": refresh, "grant_type": "refresh_token"})
        except NetworkError as exc:
            raise RuntimeError(f"Could not reach Google ({exc})") from None
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
        return {"state": self.state, "connected": self._connected_cache, "chat_attached": bool(self.chat_id), "video_id": self.video_id,
                "title": self.title, "last_error": self.last_error or self.auth.last_error, "last_poll": self.last_poll or None,
                "polls": self.polls, "quota": self.quota.status(), "redirect_uri": self.auth.redirect_uri()}

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
                wait = 30.0
            except Exception:
                logger.exception("YouTube loop error")
                self.last_error = "Unexpected error, see server logs"
                self.state = "error"
                wait = 30.0

    async def _step(self) -> float:
        await self.quota.sync()
        self._connected_cache = await self.auth.connected()
        if not self._connected_cache:
            self.state = "not_connected"
            return 5.0
        if not self.chat_id:
            return await self._detect()
        return await self._poll()

    async def _detect(self) -> float:
        interval = float(self.cfg.get("youtube_detect_interval_seconds"))
        if not self.quota.can_afford("broadcast_list"):
            self.state = "quota_low"
            return 300.0
        video = self.cfg.get("youtube_video_id")
        if video:
            await self.quota.spend(self.quota.cost("video_list"))
            status, data = await self._api("GET", "/videos", params={"part": "snippet,liveStreamingDetails", "id": video})
            item = (data.get("items") or [None])[0] if status == 200 and isinstance(data, dict) else None
            chat = ((item or {}).get("liveStreamingDetails") or {}).get("activeLiveChatId")
            title, vid = ((item or {}).get("snippet") or {}).get("title", ""), video
        elif self.cfg.get("youtube_auto_detect_live"):
            await self.quota.spend(self.quota.cost("broadcast_list"))
            status, data = await self._api("GET", "/liveBroadcasts", params={"part": "snippet,status", "broadcastStatus": "active", "broadcastType": "all"})
            item = (data.get("items") or [None])[0] if status == 200 and isinstance(data, dict) else None
            chat = ((item or {}).get("snippet") or {}).get("liveChatId")
            title, vid = ((item or {}).get("snippet") or {}).get("title", ""), (item or {}).get("id", "")
        else:
            self.state = "offline"
            return interval
        if status == 403 and _reason(data) in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"):
            await self.quota.mark_exhausted()
            self.state = "quota_low"
            return 300.0
        if status in (401, 403):
            self.last_error = f"YouTube refused the request ({_reason(data) or status}). Check the Google Cloud setup."
            self.state = "error"
            return 60.0
        if status != 200:
            self.last_error = f"YouTube answered {status} while looking for your stream."
            self.state = "error"
            return 30.0
        if not chat:
            self.state, self.last_error = "offline", ""
            return interval
        self.chat_id, self.video_id, self.title = chat, vid, title
        self._page_token, self._first_poll, self.last_error = "", True, ""
        self._stream_started = time.time()
        self.state = "live"
        self.hub.stream_state(True, title or "YouTube live stream")
        return 0.0

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
            for item in data.get("items", []):
                msg = parse_item(item)
                if msg is None:
                    continue
                if backfill:
                    if not self.cfg.get("youtube_backfill_on_connect"):
                        continue
                    msg.backfill = True
                await self.hub.ingest(msg)
            api_wait = float(data.get("pollingIntervalMillis", 0)) / 1000.0
            return max(api_wait, interval)
        reason = _reason(data)
        if reason in ("liveChatEnded", "liveChatNotFound", "liveChatDisabled") or status == 404:
            self.chat_id, self._page_token, self.title = "", "", ""
            self.state = "offline"
            self.hub.stream_state(False)
            return 5.0
        if reason in ("quotaExceeded", "dailyLimitExceeded"):
            await self.quota.mark_exhausted()
            self.state, self.last_error = "quota_low", "YouTube says the daily quota is used up. It resets at midnight Pacific Time."
            return 300.0
        if reason == "rateLimitExceeded":
            return max(interval * 2, 10.0)
        self.last_error = f"YouTube answered {status} ({reason or 'no detail'}) while reading chat."
        self.state = "error"
        return 30.0 if status >= 500 or status == 0 else 60.0

    # ------------------------------------------------------------------ actions (the ChatSource interface)
    async def preflight(self, deletes: int, action: str) -> tuple[bool, str]:
        """Check the whole approval is affordable BEFORE doing any of it, so an action is all-or-nothing."""
        await self.quota.sync()
        need = deletes * self.quota.cost("chat_delete") + (self.quota.cost("ban") if action in ("timeout", "ban") else 0)
        if self.quota.remaining < need:
            return False, f"YouTube quota too low: this needs {need} units but only {self.quota.remaining} are left today."
        return True, ""

    async def _action(self, kind: str, method: str, path: str, *, params: dict | None = None, body: Any = None) -> tuple[bool, str]:
        await self.quota.sync()
        if not self.chat_id:
            return False, "No live chat is attached right now."
        if not self.quota.can_afford(kind):
            return False, "YouTube quota exhausted for today."
        await self.quota.spend(self.quota.cost(kind))
        try:
            status, data = await self._api(method, path, params=params, body=body)
        except RuntimeError as exc:
            return False, str(exc)
        if status in (200, 204):
            return True, ""
        reason = _reason(data)
        if reason in ("quotaExceeded", "dailyLimitExceeded"):
            await self.quota.mark_exhausted()
            return False, "YouTube quota exhausted for today."
        if kind == "chat_delete" and status == 404:
            return True, ""  # already gone
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
