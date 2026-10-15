"""Serve the web UI at ``/`` without shadowing ``/api`` and ``/ws``."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from pitwall.api.errors import error_response

PLACEHOLDER = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Pitwall</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="font-family: system-ui, sans-serif; background: #111; color: #eee; padding: 2rem">
<h1>Pitwall</h1>
<p>The backend is running, but the web UI was not found (set <code>PITWALL_WEB_DIR</code>).</p>
<p>API: <a style="color: #8cf" href="/api/status">/api/status</a>,
docs: <a style="color: #8cf" href="/api/docs">/api/docs</a></p>
</body></html>
"""

_ALL_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


class NoCacheStaticFiles(StaticFiles):
    """Static files that browsers always revalidate, so a redeploy is picked up at once."""

    async def get_response(self, path: str, scope):  # noqa: ANN001, ANN201
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def install(app: FastAPI, web_dir: Path) -> None:
    """Register the API/WS catch-alls, then the UI. Call after all API routes."""

    @app.api_route("/api/{path:path}", methods=_ALL_METHODS, include_in_schema=False)
    async def api_not_found(request: Request, path: str):  # noqa: ANN202
        return error_response(404, "not_found", f"no such endpoint: /api/{path}")

    @app.websocket("/ws/{path:path}")
    async def ws_not_found(websocket: WebSocket, path: str) -> None:
        await websocket.close(code=1008)

    if (web_dir / "index.html").is_file():
        app.mount("/", NoCacheStaticFiles(directory=web_dir, html=True), name="web")
    else:

        @app.get("/", include_in_schema=False)
        async def placeholder() -> HTMLResponse:
            return HTMLResponse(PLACEHOLDER)
