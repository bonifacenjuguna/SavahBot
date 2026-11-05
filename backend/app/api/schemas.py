"""Request bodies. Pydantic validates types; the Store adds the business rules."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(_In):
    password: str = Field(min_length=1, max_length=200)


class CommandIn(_In):
    name: str
    response: str = Field(max_length=2000)
    userlevel: str = "everyone"
    cooldown: int | None = Field(default=None, ge=0, le=86400)
    user_cooldown: int | None = Field(default=None, ge=0, le=86400)
    enabled: bool = True
    aliases: list[str] = []


class CommandPatch(_In):
    name: str | None = None
    response: str | None = Field(default=None, max_length=2000)
    userlevel: str | None = None
    cooldown: int | None = Field(default=None, ge=0, le=86400)
    user_cooldown: int | None = Field(default=None, ge=0, le=86400)
    enabled: bool | None = None
    aliases: list[str] | None = None


class Preview(_In):
    template: str = Field(max_length=2000)
    user: str = "Viewer"
    level: str = "everyone"
    args: str = ""


def _interval(v: int | None) -> int | None:
    if v is not None and v != 0 and v < 60:
        raise ValueError("Time between posts must be at least 60 seconds, or 0 for none.")
    return v


class TimerIn(_In):
    name: str
    message: str = Field(max_length=500)
    interval_seconds: int = Field(default=0, ge=0, le=86400)   # 0 = no time trigger
    min_lines: int = Field(default=5, ge=0, le=1000)           # 0 = no line trigger
    enabled: bool = False
    kind: str = "recurring"                                      # recurring | once
    trigger_mode: str = "all"                                    # all | any (only matters when both triggers are set)
    run_at: float | None = None                                  # once only: earliest time (unix seconds) it may post

    _iv = field_validator("interval_seconds")(_interval)


class TimerPatch(_In):
    name: str | None = None
    message: str | None = Field(default=None, max_length=500)
    interval_seconds: int | None = Field(default=None, ge=0, le=86400)
    min_lines: int | None = Field(default=None, ge=0, le=1000)
    enabled: bool | None = None
    kind: str | None = None
    trigger_mode: str | None = None
    run_at: float | None = None

    _iv = field_validator("interval_seconds")(_interval)


class BulkIds(_In):
    ids: list[int] = Field(min_length=1, max_length=5000)
    action: str
    category: str | None = None


class QuoteIn(_In):
    body: str = Field(max_length=500)
    author: str = Field(default="", max_length=100)


class RegularIn(_In):
    ident: str = Field(max_length=200)
    label: str = Field(default="", max_length=100)


class BlacklistIn(_In):
    phrase: str = Field(max_length=200)
    is_regex: bool = False
    weight: int = Field(default=0, ge=0, le=100)
    enabled: bool = True
    category: str = "blocked_phrases"


class BlacklistItem(_In):
    phrase: str = Field(max_length=400)
    is_regex: bool = False
    weight: int = 0
    category: str = "blocked_phrases"


class BlacklistImport(_In):
    items: list[BlacklistItem] = Field(max_length=5000)
    enabled: bool = True
    dry_run: bool = False


class BlacklistPatch(_In):
    category: str | None = None
    phrase: str | None = Field(default=None, max_length=200)
    is_regex: bool | None = None
    weight: int | None = Field(default=None, ge=0, le=100)
    enabled: bool | None = None


class NoteIn(_In):
    body: str = Field(max_length=5000)
    tags: list[str] = []
    pinned: bool = False


class NotePatch(_In):
    body: str | None = Field(default=None, max_length=5000)
    tags: list[str] | None = None
    pinned: bool | None = None


class ReminderIn(_In):
    when: str = Field(max_length=100)
    text: str = Field(max_length=500)


class ChatSend(_In):
    text: str = Field(min_length=1, max_length=500)


class ModeIn(_In):
    mode: str


class SettingsPatch(_In):
    values: dict[str, str | int | float | bool]


class ScenarioIn(_In):
    name: str


class AmbientIn(_In):
    on: bool


class ModTest(_In):
    text: str = Field(max_length=1000)
    level: str = "everyone"


class AutoReplyIn(_In):
    name: str = Field(max_length=80)
    triggers: list[str] = Field(max_length=20)
    responses: list[str] = Field(max_length=10)
    match_type: str = "phrase"
    case_sensitive: bool = False
    category: str = Field(default="general", max_length=40)
    priority: int = Field(default=100, ge=1, le=1000)
    enabled: bool = False


class AutoReplyPatch(_In):
    name: str | None = Field(default=None, max_length=80)
    triggers: list[str] | None = Field(default=None, max_length=20)
    responses: list[str] | None = Field(default=None, max_length=10)
    match_type: str | None = None
    case_sensitive: bool | None = None
    category: str | None = Field(default=None, max_length=40)
    priority: int | None = Field(default=None, ge=1, le=1000)
    enabled: bool | None = None


class AutoReplyTest(_In):
    text: str = Field(max_length=500)


class NotificationsRead(_In):
    ids: list[int] | None = None
