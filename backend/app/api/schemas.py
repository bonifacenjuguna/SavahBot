"""Request bodies. Pydantic validates types; the Store adds the business rules."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


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


class TimerIn(_In):
    name: str
    message: str = Field(max_length=500)
    interval_seconds: int = Field(ge=60, le=86400)
    min_lines: int = Field(default=5, ge=0, le=1000)
    enabled: bool = False


class TimerPatch(_In):
    name: str | None = None
    message: str | None = Field(default=None, max_length=500)
    interval_seconds: int | None = Field(default=None, ge=60, le=86400)
    min_lines: int | None = Field(default=None, ge=0, le=1000)
    enabled: bool | None = None


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


class BlacklistPatch(_In):
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
