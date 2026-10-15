"""FastAPI app factory."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI, WebSocket

from pitwall import __version__
from pitwall.api import errors, static
from pitwall.api.routes_sessions import router as sessions_router
from pitwall.api.routes_setup import router as setup_router
from pitwall.api.routes_status import router as status_router
from pitwall.config import Config
from pitwall.services.container import Services


def create_app(config: Config | None = None, *, udp: bool = True) -> FastAPI:
    """Build the app. ``udp=False`` skips binding the UDP socket (tests)."""
    config = config or Config.from_env()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        services = Services(config)
        app.state.services = services
        try:
            await services.start(udp=udp)
            yield
        finally:
            await services.stop()

    app = FastAPI(
        title="Pitwall",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    errors.install(app)
    app.include_router(status_router)
    app.include_router(sessions_router)
    app.include_router(setup_router)

    @app.websocket("/ws/live")
    async def ws_live(websocket: WebSocket) -> None:
        await websocket.app.state.services.hub.serve(websocket)

    static.install(app, config.web_dir)
    return app
