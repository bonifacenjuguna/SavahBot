"""Demo mode: a simulated stream chat that runs through exactly the same pipeline as live chat.

Nothing here touches YouTube. Moderation actions taken in demo mode are marked "simulated". Use the
scenarios to see how each algorithm behaves and to tune weights before going live.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, Awaitable, Callable

from ..models import ChatMessage

logger = logging.getLogger("savahbot.demo")

VIEWER_NAMES = ["Wanjiru", "Kamau", "Achieng", "Otieno", "Zawadi", "Baraka", "Neema", "Juma", "Imani", "Tumaini",
                "Zuri", "Kofi", "Amara", "Daudi", "Femi", "Lulu", "Sefu", "Nia", "Tendai", "Ayana"]
CHAT_LINES = [
    "hello everyone!", "gg that was close", "what game is this?", "LET'S GOOO", "first time here, loving it",
    "that play was clean", "how long have you been streaming?", "lol", "can you show the settings?",
    "the music is great", "hi from Nairobi", "chat is moving fast today", "nice one", "no way, he actually did it",
    "good luck on this level", "what's the plan for today?", "that boss is tough", "haha", "who else is watching late?",
    "I missed the start, what happened?", "great stream as always", "the new overlay looks sharp",
    "any tips for beginners?", "this part is my favourite", "wait, rewind that",
]
COMMAND_LINES = ["!uptime", "!quote", "!commands", "!hello", "!dice", "!8ball will we win?"]
SPAM_LINES = [
    "FREE ROBUX at robux-gift.xyz hurry before it ends", "check my channel for free giftcards now",
    "Fr33 V-Bucks click my profile", "double your bitcoin guaranteed crypto giveaway",
]

SCENARIOS: dict[str, dict[str, str]] = {
    "friendly_chat": {"label": "Friendly chat", "description": "Normal viewers chatting. Nothing should be flagged."},
    "spam_raid": {"label": "Copy-paste raid", "description": "Six new accounts post near-identical text with random numbers (SimHash raid detector)."},
    "link_spammer": {"label": "Link spammer", "description": "A new account posts a banned phrase plus a link (blacklist + link + new-chatter)."},
    "caps_flood": {"label": "Shouting", "description": "Capital letters and stretched characters (caps + repetition)."},
    "flood": {"label": "Message flood", "description": "One new account sends eight messages in two seconds (sliding-window rate limit)."},
    "bot_timing": {"label": "Clockwork bot", "description": "An account posts every five seconds on the dot (timing analysis). Takes about 35 seconds."},
    "disguised_words": {"label": "Disguised words", "description": "Leetspeak, look-alike letters and spacing hide a banned phrase (normalisation + Aho-Corasick)."},
    "commands": {"label": "Commands", "description": "Viewers use !hello, !uptime, !quote, !dice and !commands."},
    "scam_wave": {"label": "Scam messages", "description": "Four different scams: a crypto doubler, a fake channel warning, fake support and a fake prize (scam packs, scam intent, link intelligence)."},
    "typo_scam": {"label": "Typos and disguises", "description": "Misspelt and stretched-out scam phrases ('frree robus', 'd0uble ur b1tcoin') that exact matching alone would miss (typo matching)."},
    "lookalike_links": {"label": "Look-alike links", "description": "youtub3.com, a Nitro gift site, a short link and a bare IP address (link intelligence)."},
    "impersonator": {"label": "Impersonator", "description": "Accounts named like the streamer's support team claim to be staff (impersonation guard)."},
    "art_spam": {"label": "Text tricks", "description": "Zalgo text, Cyrillic look-alikes, hidden characters and symbol art (text-trick detection)."},
    "swahili_scam": {"label": "Swahili scams", "description": "'Nimekutumia pesa kwa makosa', a fake prize and sub-for-sub in Swahili (language packs)."},
    "raid_wave": {"label": "Raid wave", "description": "Eight brand-new accounts arrive within seconds, then one posts a suspicious line (raid wave tracker). Takes about 12 seconds."},
    "warnings_and_questions": {"label": "Warnings and questions", "description": "Viewers warn each other about a scam and ask if it is real. Nothing should be flagged (context awareness)."},
    "gaming_talk": {"label": "Gaming talk", "description": "'Kill streak', 'nuke incoming', 'I'm dead lol'. Nothing should be flagged (safe phrases)."},
    "mixed": {"label": "Everything", "description": "Runs friendly chat, commands, disguised words and a raid back to back."},
}


class DemoSource:
    name = "demo"

    def __init__(self, cfg: Any, hub: Any, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep, rng: random.Random | None = None) -> None:
        self.cfg = cfg
        self.hub = hub
        self.clock = clock
        self._sleep = sleep
        seed = cfg.get("demo_seed")
        self.rng = rng or (random.Random(seed) if seed else random.Random())
        self._tasks: set[asyncio.Task] = set()
        self._ambient: asyncio.Task | None = None
        self._line_used: dict[str, float] = {}
        self._counter = 0
        self.running = False
        self.active_scenarios: set[str] = set()

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.hub.stream_state(True, f"{self.cfg.get('demo_channel_name')} (demo stream)")
        if self.cfg.get("demo_enabled") and self.cfg.get("demo_autostart"):
            self.set_ambient(True)

    async def stop(self) -> None:
        self.running = False
        for t in list(self._tasks) + ([self._ambient] if self._ambient else []):
            t.cancel()
        await asyncio.gather(*self._tasks, *([self._ambient] if self._ambient else []), return_exceptions=True)
        self._tasks.clear()
        self._ambient = None
        self.active_scenarios.clear()

    def set_ambient(self, on: bool) -> None:
        if on and (self._ambient is None or self._ambient.done()):
            self._ambient = asyncio.ensure_future(self._ambient_loop())
        elif not on and self._ambient is not None:
            self._ambient.cancel()
            self._ambient = None

    def status(self) -> dict[str, Any]:
        return {"state": "running" if self.running else "stopped", "ambient": bool(self._ambient and not self._ambient.done()),
                "scenarios_running": sorted(self.active_scenarios), "channel": self.cfg.get("demo_channel_name")}

    # ------------------------------------------------------------------ actions are simulated
    async def send(self, text: str) -> bool:
        await self._post("SavahBot", "bot", text, "bot", from_bot=True)
        return True

    async def delete(self, msg_id: str) -> tuple[bool, str]:
        return True, ""

    async def timeout(self, author_id: str, seconds: int) -> tuple[bool, str]:
        return True, ""

    async def ban(self, author_id: str) -> tuple[bool, str]:
        return True, ""

    # ------------------------------------------------------------------ message helpers
    async def _post(self, name: str, author_id: str, text: str, level: str = "everyone", from_bot: bool = False) -> None:
        self._counter += 1
        await self.hub.ingest(ChatMessage(
            platform="demo", author_id=author_id, author_name=name, text=text, level=level, ts=self.clock(),
            msg_id=f"demo-{self._counter}", demo=True, from_bot=from_bot))

    def _viewer(self) -> tuple[str, str, str]:
        pool = VIEWER_NAMES[: max(3, self.cfg.get("demo_chatter_count"))]
        name = self.rng.choice(pool)
        # A fixed cast makes the demo easy to read: one moderator, two members, two regulars, the rest viewers.
        level = ("mod" if name == pool[0] else "member" if name in pool[1:3] else "regular" if name in pool[3:5] else "everyone")
        return name, f"demo-{name.lower()}", level

    def _newcomer(self, prefix: str = "viewer") -> tuple[str, str]:
        name = f"{prefix}{self.rng.randint(1000, 9999)}"
        return name, f"demo-{name.lower()}"

    async def _ambient_loop(self) -> None:
        try:
            while True:
                rate = max(1, self.cfg.get("demo_messages_per_minute"))
                await self._sleep(self.rng.expovariate(rate / 60.0))
                if self.rng.random() < self.cfg.get("demo_spam_probability"):
                    name, aid = self._newcomer("promo")
                    await self._post(name, aid, self.rng.choice(SPAM_LINES))
                    continue
                name, aid, level = self._viewer()
                pool = COMMAND_LINES if self.rng.random() < 0.06 else CHAT_LINES
                now = self.clock()
                # A line is not reused for 3 minutes: the same words from several accounts would read as a raid.
                fresh = [t for t in pool if now - self._line_used.get(t, -1e9) > 180] or [min(pool, key=lambda t: self._line_used.get(t, -1e9))]
                text = self.rng.choice(fresh)
                self._line_used[text] = now
                await self._post(name, aid, text, level)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Demo ambient loop stopped")

    # ------------------------------------------------------------------ scenarios
    def scenarios(self) -> list[dict[str, Any]]:
        return [{"name": k, **v, "running": k in self.active_scenarios} for k, v in SCENARIOS.items()]

    def start_scenario(self, name: str) -> bool:
        if name not in SCENARIOS or not self.running or name in self.active_scenarios:
            return False
        self.active_scenarios.add(name)
        task = asyncio.ensure_future(self._run_scenario(name))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    async def run_scenario(self, name: str) -> None:
        """Run a scenario to completion in the caller's task (used by tests)."""
        self.active_scenarios.add(name)
        await self._run_scenario(name)

    async def _run_scenario(self, name: str) -> None:
        try:
            await getattr(self, f"_sc_{name}")()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Demo scenario %s failed", name)
        finally:
            self.active_scenarios.discard(name)

    async def _sc_friendly_chat(self) -> None:
        for _ in range(8):
            n, a, lv = self._viewer()
            await self._post(n, a, self.rng.choice(CHAT_LINES), lv)
            await self._sleep(self.rng.uniform(1.5, 3.5))

    async def _sc_spam_raid(self) -> None:
        # Neither text is on the banned-phrase list, so this scenario isolates the cross-account similarity detector.
        base = self.rng.choice(["Join my giveaway channel for free subs", "Giveaway happening now on my page, join in fast"])
        for _ in range(6):
            n, a = self._newcomer("GiftHunter")
            await self._post(n, a, f"{base} {self.rng.randint(1000, 9999)}")
            await self._sleep(self.rng.uniform(0.6, 1.4))

    async def _sc_link_spammer(self) -> None:
        n, a = self._newcomer("promo")
        await self._post(n, a, "FREE ROBUX at robux-gift.xyz right now everybody")

    async def _sc_caps_flood(self) -> None:
        n, a = self._newcomer("loud")
        await self._post(n, a, "WOOOOOOOOOOOOW THIS STREAMER IS THE BEST EVER SUBSCRIBE NOW")

    async def _sc_flood(self) -> None:
        n, a = self._newcomer("flooder")
        words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"]
        for w in words:
            await self._post(n, a, f"message about {w}")
            await self._sleep(0.25)

    async def _sc_bot_timing(self) -> None:
        n, a = self._newcomer("autobot")
        topics = ["sunrise", "harbour", "lantern", "meadow", "compass", "orchard", "glacier"]
        for t in topics:
            await self._post(n, a, f"daily update about the {t}")
            await self._sleep(5.0)

    async def _sc_disguised_words(self) -> None:
        n, a = self._newcomer("sneaky")
        await self._post(n, a, "Fr33 R0bux at my pr0file, f r e e  v - b u c k s too")

    async def _sc_scam_wave(self) -> None:
        for text in ("Double your bitcoin! Send 0.1 BTC and get 0.2 BTC back, whatsapp me +254712345678",
                     "Your channel will be removed. Verify now at bit.ly/yt-verify",
                     "Customer support number 0712 345 678, call now to claim your refund",
                     "CONGRATULATIONS you have been selected as the winner! Claim your prize at claim-prize-now.top"):
            n, a = self._newcomer("promo")
            await self._post(n, a, text)
            await self._sleep(1.2)

    async def _sc_typo_scam(self) -> None:
        for text in ("frree robus click my pr0file", "d0uble ur b1tcoin n0w guaranteed profit", "cl4im ur fr33 g1ft cards at the link"):
            n, a = self._newcomer("sneaky")
            await self._post(n, a, text)
            await self._sleep(1.2)

    async def _sc_lookalike_links(self) -> None:
        for text in ("Verify your account at youtub3.com/verify", "Free gift for everyone: discord-nitro.gift",
                     "Check this out bit.ly/3xYzAb", "Log in here http://192.168.1.50/youtube"):
            n, a = self._newcomer("linker")
            await self._post(n, a, text)
            await self._sleep(1.2)

    async def _sc_impersonator(self) -> None:
        channel = str(self.cfg.get("demo_channel_name"))
        await self._post(f"{channel}_Support", "demo-impostor-1", "Hello! I am the admin of this stream. Send your details to receive the reward.")
        await self._sleep(1.5)
        await self._post("YouTube Support Team", "demo-impostor-2", "Your channel is at risk. Reply here to verify.")

    async def _sc_art_spam(self) -> None:
        for text in ("h\u0300\u0301\u0302\u0303e\u0300\u0301\u0302\u0303l\u0300\u0301\u0302\u0303l\u0300\u0301\u0302\u0303o\u0300\u0301\u0302\u0303 everyone",
                     "fr\u0435e r\u043ebux at my profile",
                     "w\u200ba\u200bt\u200bc\u200bh my stream",
                     "\u2588\u2588\u2588\u2588\u2593\u2593\u2593\u2593\u2592\u2592\u2592\u2592\u2591\u2591\u2591\u2591 \u2588\u2588\u2588\u2588\u2593\u2593\u2593\u2593"):
            n, a = self._newcomer("artist")
            await self._post(n, a, text)
            await self._sleep(1.2)

    async def _sc_swahili_scam(self) -> None:
        for text in ("Nimekutumia pesa kwa makosa tafadhali rudisha", "Umechaguliwa kushinda! Pokea zawadi yako bonyeza link hii",
                     "Pata pesa haraka mtandaoni wasiliana nasi whatsapp", "Nisub nikusub tuongezane subscribers"):
            n, a = self._newcomer("mgeni")
            await self._post(n, a, text)
            await self._sleep(1.2)

    async def _sc_raid_wave(self) -> None:
        hellos = ("hi everyone", "hello from nairobi", "just got here", "what are we playing", "mambo vipi", "first time here",
                  "hey chat", "good evening")
        for text in hellos:
            n, a = self._newcomer("arrival")
            await self._post(n, a, text)
            await self._sleep(0.9)
        n, a = self._newcomer("lateguest")
        await self._post(n, a, "claim your prize now")
        await self._sleep(1.0)
        n, a = self._newcomer("lateguest")
        await self._post(n, a, "nice stream everyone")

    async def _sc_warnings_and_questions(self) -> None:
        for text in ("don't click that link, it's a scam bot", "is that elon musk giveaway real or a scam?", "mods please ban that bot",
                     "never share your seed phrase with anyone"):
            n, a = self._newcomer("careful")
            await self._post(n, a, text)
            await self._sleep(1.5)

    async def _sc_gaming_talk(self) -> None:
        for text in ("kill streak! he is dead lol", "nuke incoming run", "that headshot was insane, destroyed him", "clutch or kick, rush b"):
            n, a = self._newcomer("gamer")
            await self._post(n, a, text)
            await self._sleep(1.5)

    async def _sc_commands(self) -> None:
        for line in ["!hello", "!uptime", "!quote", "!dice", "!commands"]:
            n, a, lv = self._viewer()
            await self._post(n, a, line, lv)
            await self._sleep(1.5)

    async def _sc_mixed(self) -> None:
        for step in (self._sc_friendly_chat, self._sc_commands, self._sc_disguised_words, self._sc_spam_raid):
            await step()
            await self._sleep(2.0)
