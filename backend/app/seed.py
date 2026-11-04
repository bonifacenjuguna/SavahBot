"""Starter content created once on first boot (turn off with COMMAND_SEED_DEFAULTS=false)."""
from __future__ import annotations

import logging
from typing import Any

from .store import Store, ValidationFailed

logger = logging.getLogger("savahbot.seed")

COMMANDS = [
    ("hello", "Hello $(user)! Welcome to the stream.", "everyone"),
    ("lurk", "$(user) is lurking. Enjoy the quiet!", "everyone"),
    ("dice", "$(user) rolled a $(random 1-6).", "everyone"),
    ("8ball", "$(choose Yes|No|Maybe|Ask again later|Definitely|Not a chance|Signs point to yes)", "everyone"),
    ("time", "It is $(time) for the streamer.", "everyone"),
    ("math", "$(args) = $(math $(args))", "everyone"),
    ("deaths", "Deaths so far: $(count)", "mod"),
]
TIMERS = [("follow-reminder", "Enjoying the stream? Subscribe and turn on notifications so you never miss one!", 900, 10)]
QUOTES = ["The best stream is the one you actually start.", "Chat is the co-host."]
BLACKLIST = [
    "free robux", "free v-bucks", "crypto giveaway", "double your bitcoin", "sub4sub", "check my channel",
    "click my profile", "make money fast", "free giftcards", "whatsapp me", "telegram me",
]


async def seed_defaults(db: Any, store: Store) -> bool:
    if await db.kv_get("seeded"):
        return False
    for name, response, level in COMMANDS:
        try:
            await store.create_command(name, response, userlevel=level)
        except ValidationFailed:
            pass
    for name, message, interval, lines in TIMERS:
        try:
            await store.create_timer(name, message, interval, lines, enabled=False)  # off until you enable it
        except ValidationFailed:
            pass
    for q in QUOTES:
        await store.add_quote(q, author="SavahBot")
    for phrase in BLACKLIST:
        try:
            await store.add_blacklist(phrase)
        except ValidationFailed:
            pass
    await db.kv_set("seeded", "1")
    logger.info("Seeded starter commands, timers, quotes and banned phrases")
    return True
