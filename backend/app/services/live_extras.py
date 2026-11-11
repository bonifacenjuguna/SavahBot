"""What happens around the chat while you are live: members, Super Chats, gifts, new subscribers, and live likes and viewers.

Everything here is best effort and says so. YouTube decides what it reveals: likes can be hidden by the creator, viewer counts lag, and the
list of recent subscribers only holds people who made their subscription public. Nothing here guesses a number it was not given.
Message text is never stored; only who, what kind and how much.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from ..db import register_schema

logger = logging.getLogger(__name__)

register_schema([
    "CREATE TABLE IF NOT EXISTS stream_events (id {PK}, ts {REAL} NOT NULL, event_id TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL, author_id TEXT NOT NULL DEFAULT '', author_name TEXT NOT NULL DEFAULT '', amount TEXT NOT NULL DEFAULT '', count INTEGER NOT NULL DEFAULT 1, video_id TEXT NOT NULL DEFAULT '')",
    "CREATE INDEX IF NOT EXISTS idx_stream_events_ts ON stream_events (ts)",
    "CREATE TABLE IF NOT EXISTS live_samples (id {PK}, ts {REAL} NOT NULL, video_id TEXT NOT NULL, likes INTEGER, viewers INTEGER)",
    "CREATE INDEX IF NOT EXISTS idx_live_samples_video ON live_samples (video_id, ts)",
])

EVENT_TYPES = {"newSponsorEvent": "member", "memberMilestoneChatEvent": "member_milestone", "superChatEvent": "superchat", "superStickerEvent": "supersticker",
               "membershipGiftingEvent": "gift", "giftMembershipReceivedEvent": "gift_received"}
LABEL = {"member": "joined as a member", "member_milestone": "reached a membership milestone", "superchat": "sent a Super Chat", "supersticker": "sent a Super Sticker",
         "gift": "gifted memberships", "gift_received": "received a gifted membership"}
CATEGORY = {"member": "stream.member", "member_milestone": "stream.member", "gift": "stream.member", "gift_received": "stream.member", "superchat": "stream.superchat", "supersticker": "stream.superchat"}


def parse_event(item: dict[str, Any]) -> dict[str, Any] | None:
    """A chat item that is an event rather than chat text, reduced to who, what and how much. The viewer's comment is not kept."""
    sn, ad = item.get("snippet") or {}, item.get("authorDetails") or {}
    kind = EVENT_TYPES.get(sn.get("type"))
    if kind is None:
        return None
    amount, count = "", 1
    if kind == "superchat":
        amount = (sn.get("superChatDetails") or {}).get("amountDisplayString", "")
    elif kind == "supersticker":
        amount = (sn.get("superStickerDetails") or {}).get("amountDisplayString", "")
    elif kind == "gift":
        count = int((sn.get("membershipGiftingDetails") or {}).get("giftMembershipsCount") or 1)
    elif kind == "member_milestone":
        count = int((sn.get("memberMilestoneChatDetails") or {}).get("memberMonth") or 1)
    return {"event_id": item.get("id", ""), "kind": kind, "author_id": ad.get("channelId") or sn.get("authorChannelId", ""),
            "author_name": ad.get("displayName", "someone"), "amount": str(amount)[:30], "count": max(1, count)}


def _fill(template: str, **vals: Any) -> str:
    """Put $(user), $(amount) and $(count) in. Values cannot smuggle in their own $( so a display name never becomes a command."""
    for k, v in vals.items():
        template = template.replace(f"$({k})", str(v).replace("$(", "$ ("))
    return template


class LiveExtras:
    def __init__(self, c: Any) -> None:
        self.c, self.cfg, self.db = c, c.cfg, c.db
        self._seen: set[str] = set()
        self._subs_seen: set[str] | None = None
        self._subs_next = 0.0
        self._sub_count: int | None = None
        self._live_next = 0.0
        self.live: dict[str, Any] = {"video_id": "", "likes": None, "viewers": None, "updated": 0.0, "peak_viewers": 0, "likes_hidden": False, "note": ""}
        self._viewer_marks: set[int] = set()
        self._likes_mark: int | None = None
        self.subs: dict[str, Any] = {"state": "idle", "note": "", "count": None, "checked": 0.0}

    # ------------------------------------------------------------------ chat events
    async def handle(self, ev: dict[str, Any], video_id: str = "", backfill: bool = False) -> None:
        if backfill or (ev["event_id"] and ev["event_id"] in self._seen):
            return
        if ev["event_id"]:
            self._seen.add(ev["event_id"])
            if len(self._seen) > 2000:
                self._seen = set(list(self._seen)[-1000:])
        now = time.time()
        await self.db.execute("INSERT INTO stream_events (ts, event_id, kind, author_id, author_name, amount, count, video_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                              (now, ev["event_id"], ev["kind"], ev["author_id"], ev["author_name"], ev["amount"], ev["count"], video_id))
        if self.cfg.get("yt_events_notify"):
            what = LABEL[ev["kind"]] + (f" ({ev['amount']})" if ev["amount"] else f" ({ev['count']})" if ev["kind"] in ("gift", "member_milestone") and ev["count"] > 1 else "")
            await self.c.notifier.emit(CATEGORY[ev["kind"]], f"{ev['author_name']} {what}", "", key=ev["event_id"] or f"{ev['kind']}:{ev['author_id']}:{int(now)}")
        if self.cfg.get("yt_events_thank") and ev["kind"] in ("member", "superchat", "supersticker", "gift"):
            key = {"member": "member", "superchat": "superchat", "supersticker": "superchat", "gift": "gift"}[ev["kind"]]
            await self.c.hub.send_chat(_fill(self.cfg.get(f"yt_events_msg_{key}"), user=ev["author_name"], amount=ev["amount"], count=ev["count"]), render=True)

    async def recent_events(self, limit: int = 30) -> list[dict[str, Any]]:
        return await self.db.fetchall("SELECT ts, kind, author_name, amount, count FROM stream_events ORDER BY id DESC LIMIT ?", (max(1, min(limit, 100)),))

    # ------------------------------------------------------------------ scheduled work (leader only, called by the scheduler every few seconds)
    async def tick(self, now: float) -> None:
        yt = getattr(self.c, "youtube", None)
        if yt is None or yt.state != "live" or not yt.video_id or self.c.hub.mode != "live":
            return
        try:
            if self.cfg.get("yt_live_enabled") and now >= self._live_next:
                self._live_next = now + max(30, min(600, int(self.cfg.get("yt_live_seconds"))))
                await self._live_stats(yt, now)
            if self.cfg.get("yt_subs_enabled") and now >= self._subs_next:
                self._subs_next = now + 60 * max(5, min(120, int(self.cfg.get("yt_subs_minutes"))))
                await self._subscribers(yt, now)
        except Exception:
            logger.exception("Live extras failed")

    async def _live_stats(self, yt: Any, now: float) -> None:
        q = self.c.quota
        if not q.can_afford("video_list"):
            self.live["note"] = "Paused: the daily YouTube quota is nearly used up."
            return
        await q.spend(q.cost("video_list"))
        status, data = await yt._api("GET", "/videos", params={"part": "statistics,liveStreamingDetails", "id": yt.video_id})
        if status != 200 or not isinstance(data, dict) or not data.get("items"):
            self.live["note"] = f"YouTube answered {status} for the live stats."
            return
        item = data["items"][0]
        st, ld = item.get("statistics") or {}, item.get("liveStreamingDetails") or {}
        likes = int(st["likeCount"]) if "likeCount" in st else None
        viewers = int(ld["concurrentViewers"]) if "concurrentViewers" in ld else None
        if yt.video_id != self.live["video_id"]:
            self.live.update(video_id=yt.video_id, peak_viewers=0)
            self._viewer_marks, self._likes_mark = set(), None
        self.live.update(likes=likes, viewers=viewers, updated=now, likes_hidden=likes is None,
                         note="" if likes is not None else "The creator hides the like count on this video, so YouTube does not share it.")
        self.live["peak_viewers"] = max(self.live["peak_viewers"], viewers or 0)
        await self.db.execute("INSERT INTO live_samples (ts, video_id, likes, viewers) VALUES (?, ?, ?, ?)", (now, yt.video_id, likes, viewers))
        await self._live_milestones(likes, viewers)

    async def _live_milestones(self, likes: int | None, viewers: int | None) -> None:
        step = int(self.cfg.get("yt_live_likes_step"))
        if likes is not None and step > 0:
            mark = likes // step * step
            if self._likes_mark is None:
                self._likes_mark = mark            # the first reading only sets the baseline
            elif mark > self._likes_mark:
                self._likes_mark = mark
                await self.c.notifier.emit("stream.milestone", f"{mark:,} likes", "Your stream passed a likes milestone.", key=f"likes:{self.live['video_id']}:{mark}")
        vstep = int(self.cfg.get("yt_live_viewers_step"))
        if viewers is not None and vstep > 0:
            mark = viewers // vstep * vstep
            if mark > 0 and mark not in self._viewer_marks:
                self._viewer_marks.update(range(vstep, mark + 1, vstep))
                await self.c.notifier.emit("stream.milestone", f"{mark:,} watching at once", "A new high for this stream.", key=f"viewers:{self.live['video_id']}:{mark}")

    async def _subscribers(self, yt: Any, now: float) -> None:
        """Two honest sources: the recent-subscribers list (names, but only public subscribers) and the channel's subscriber count (a number, no names)."""
        q = self.c.quota
        if not q.can_afford("subscription_list"):
            self.subs.update(state="paused", note="Paused: the daily YouTube quota is nearly used up.")
            return
        await q.spend(q.cost("subscription_list"))
        status, data = await yt._api("GET", "/subscriptions", params={"part": "subscriberSnippet", "myRecentSubscribers": "true", "maxResults": 10})
        self.subs["checked"] = now
        if status == 200 and isinstance(data, dict):
            current = {i.get("subscriberSnippet", {}).get("channelId", ""): i.get("subscriberSnippet", {}).get("title", "someone") for i in data.get("items", [])}
            current.pop("", None)
            if self._subs_seen is None:
                self._subs_seen = set(current)                      # first look: remember who is already there, alert about nobody
            else:
                for cid, name in current.items():
                    if cid in self._subs_seen:
                        continue
                    self._subs_seen.add(cid)
                    await self.db.execute("INSERT INTO stream_events (ts, event_id, kind, author_id, author_name, video_id) VALUES (?, ?, 'subscriber', ?, ?, ?)", (now, f"sub:{cid}", cid, name, yt.video_id))
                    await self.c.notifier.emit("stream.subscriber", f"{name} subscribed", "", key=f"sub:{cid}")
                    if self.cfg.get("yt_subs_thank"):
                        await self.c.hub.send_chat(_fill(self.cfg.get("yt_subs_msg"), user=name), render=True)
            self.subs.update(state="ok", note="Only subscribers who made their subscription public can appear here.")
        elif status in (401, 403):
            self.subs.update(state="needs_access", note="YouTube did not allow the subscriber list. Sign in to Google again from Setup and allow access to your subscribers, or rely on the subscriber count below.")
        else:
            self.subs.update(state="error", note=f"YouTube answered {status} for the subscriber list.")
        await self._sub_count_check(yt)

    async def _sub_count_check(self, yt: Any) -> None:
        q = self.c.quota
        if not q.can_afford("channel_list"):
            return
        await q.spend(q.cost("channel_list"))
        status, data = await yt._api("GET", "/channels", params={"part": "statistics", "mine": "true"})
        if status != 200 or not isinstance(data, dict) or not data.get("items"):
            return
        st = data["items"][0].get("statistics") or {}
        if st.get("hiddenSubscriberCount") or "subscriberCount" not in st:
            self.subs["count"] = None
            return
        n = int(st["subscriberCount"])
        old, self._sub_count, self.subs["count"] = self._sub_count, n, n
        step = int(self.cfg.get("yt_subs_milestone_step"))
        if old is not None and step > 0 and n // step > old // step:
            await self.c.notifier.emit("stream.milestone", f"{n // step * step:,} subscribers", "Your channel passed a subscriber milestone.", key=f"subs:{n // step * step}")

    # ------------------------------------------------------------------ for the dashboard
    async def stats(self) -> dict[str, Any]:
        vid = self.live["video_id"]
        rows = await self.db.fetchall("SELECT ts, likes, viewers FROM live_samples WHERE video_id = ? ORDER BY ts DESC LIMIT 360", (vid,)) if vid else []
        rows.reverse()
        per_min = None
        with_likes = [r for r in rows if r["likes"] is not None]
        if len(with_likes) >= 2 and with_likes[-1]["ts"] > with_likes[0]["ts"]:
            window = [r for r in with_likes if r["ts"] >= with_likes[-1]["ts"] - 600] or with_likes
            span = max(1.0, window[-1]["ts"] - window[0]["ts"])
            per_min = round(max(0, window[-1]["likes"] - window[0]["likes"]) * 60 / span, 1) if window[-1]["ts"] > window[0]["ts"] else None
        cost = self.c.quota.cost("video_list")
        secs = max(30, min(600, int(self.cfg.get("yt_live_seconds"))))
        return {**self.live, "likes_per_min": per_min, "series": rows, "sample": False, "subscribers": self.subs,
                "cost_per_hour": round(3600 / secs * cost), "enabled": bool(self.cfg.get("yt_live_enabled"))}

    async def streams(self, limit: int = 20) -> list[dict[str, Any]]:
        """One row per past stream that has samples: for the Insights page."""
        return await self.db.fetchall("SELECT video_id, MIN(ts) AS started, MAX(ts) AS ended, MAX(viewers) AS peak_viewers, MAX(likes) AS likes, COUNT(*) AS samples FROM live_samples GROUP BY video_id ORDER BY started DESC LIMIT ?", (max(1, min(limit, 60)),))
