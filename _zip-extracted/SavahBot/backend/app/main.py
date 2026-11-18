"""ASGI entry point.

    uvicorn app.main:create_app --factory --host 0.0.0.0 --port $PORT

(`--factory` builds the app on start-up, so importing this module never touches the database.)
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route

from .api.routes import R
from .container import Container


class SecurityHeaders:
    """Adds the response headers every API answer should carry, without touching a header a route already set (the live feed and the public voice
    files choose their own caching). Plain ASGI on purpose: a streaming response such as the live feed passes through untouched."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def wrapped(message) -> None:
            if message["type"] == "http.response.start":
                names = {k.lower() for k, _ in message.get("headers", [])}
                extra = [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer")]
                if scope["path"].startswith("/api/"):
                    extra.append((b"cache-control", b"no-store"))     # signed-in answers are never kept by a browser or a proxy
                message = {**message, "headers": [*message.get("headers", []), *[h for h in extra if h[0] not in names]]}
            await send(message)

        await self.app(scope, receive, wrapped)


def create_app(container: Container | None = None) -> Starlette:
    c = container or Container()
    logging.basicConfig(level=getattr(logging, str(c.settings.log_level).upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: Starlette):
        await c.start()
        try:
            yield
        finally:
            await c.stop()

    async def root(request):
        return JSONResponse({"app": c.settings.app_name, "ok": True, "hint": "This is the SavahBot API. Open the dashboard to use it."})

    app = Starlette(
        routes=[Route("/", root), *R.routes],
        middleware=[Middleware(SecurityHeaders), Middleware(CORSMiddleware, allow_origins=c.settings.cors_list, allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
                               allow_headers=["Authorization", "Content-Type"], allow_credentials=False, max_age=600)],
        lifespan=lifespan,
    )
    app.state.c = c
    return app
