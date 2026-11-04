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
        middleware=[Middleware(CORSMiddleware, allow_origins=c.settings.cors_list, allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
                               allow_headers=["Authorization", "Content-Type"], allow_credentials=False, max_age=600)],
        lifespan=lifespan,
    )
    app.state.c = c
    return app
