"""Backup & Recovery API: encrypted export, verify, import, undo, and the guarded first-run restore."""
from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.requests import Request

from ..access.service import AccessError
from ..backup.container import BackupError
from .routes import ApiError, R, client_ip, parse

logger = logging.getLogger("savahbot.backup")


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Export(_In):
    scopes: list[str] = Field(max_length=20)
    passphrase: str = Field(default="", max_length=200)


class Open(_In):
    data: str = Field(min_length=1)
    key: str = Field(min_length=1, max_length=200)
    passphrase: str = Field(default="", max_length=200)


class Import(Open):
    mode: str = "merge"
    scopes: list[str] = Field(default_factory=list, max_length=20)
    dry_run: bool = False


def _guard(fn):
    async def inner(request: Request, c: Any) -> Any:
        try:
            return await fn(request, c)
        except BackupError as exc:
            raise ApiError(str(exc), 400) from exc
        except (ApiError, AccessError, ValidationError, ValueError, KeyError, PermissionError):     # the shared handler already words these
            raise
        except Exception as exc:     # 1.4.3: a bare "Something went wrong" told you nothing; name the step that failed (details are in the server log)
            logger.exception("Backup step failed")
            raise ApiError(f"The backup step failed: {type(exc).__name__}: {str(exc)[:200]}", 500) from exc
    return inner


@R.add("/backup/info", ["GET"])
@_guard
async def info(request: Request, c: Any) -> dict:
    return await c.backup.info()


@R.add("/backup/export", ["POST"])
@_guard
async def export(request: Request, c: Any) -> dict:
    c.access.require_fresh(request.state.session)
    b = await parse(request, Export)
    out = await c.backup.export(b.scopes, b.passphrase)
    await c.access.audit("backup_exported", request.state.session, "", ", ".join(out["scopes"]))
    await c.access._alert(f"📦 An encrypted backup was exported ({', '.join(out['scopes'])}).")
    return out


@R.add("/backup/verify", ["POST"])
@_guard
async def verify(request: Request, c: Any) -> dict:
    b = await parse(request, Open)
    return await c.backup.verify(b.data, b.key, b.passphrase)


@R.add("/backup/import", ["POST"])
@_guard
async def import_(request: Request, c: Any) -> dict:
    b = await parse(request, Import)
    if not b.dry_run:
        c.access.require_fresh(request.state.session)
    return await c.backup.import_(b.data, b.key, b.passphrase, b.mode, b.scopes, b.dry_run)


@R.add("/backup/undo", ["POST"])
@_guard
async def undo(request: Request, c: Any) -> dict:
    c.access.require_fresh(request.state.session)
    return await c.backup.undo()


# ---- fresh deployment: restore BEFORE signing in. Needs the one-time token printed in the server logs; dies when anyone signs in.
@R.add("/backup/first-run", ["GET"], public=True)
async def first_run_status(request: Request, c: Any) -> dict:
    return {"available": await c.backup.fresh() and bool(await c.db.kv_get("restore_token_hash"))}


class FirstRun(Import):
    token: str = Field(min_length=1, max_length=100)


@R.add("/backup/first-run", ["POST"], public=True)
@_guard
async def first_run_import(request: Request, c: Any) -> dict:
    b = await parse(request, FirstRun)
    await c.backup.check_token(b.token, client_ip(request))
    out = await c.backup.import_(b.data, b.key, b.passphrase, b.mode if b.mode in ("merge", "replace") else "replace", b.scopes, b.dry_run)
    if not b.dry_run:
        await c.backup.burn_token()
    return out
