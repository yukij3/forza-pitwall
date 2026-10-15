"""Sessions, laps, traces and per-lap / per-session analysis."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from pitwall.api.convert import build_trace, public_lap, public_session
from pitwall.api.deps import ServicesDep
from pitwall.api.errors import ApiError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


class SessionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = None


@router.get("/sessions")
async def list_sessions(services: ServicesDep) -> list[dict[str, Any]]:
    rec = services.recorder.session_id
    return [public_session(s, recording_id=rec) for s in services.store.list_sessions()]


@router.get("/sessions/{session_id}")
async def get_session(services: ServicesDep, session_id: int) -> dict[str, Any]:
    session = public_session(
        services.store.get_session(session_id), recording_id=services.recorder.session_id
    )
    session["laps"] = [public_lap(lap) for lap in services.store.list_laps(session_id)]
    return session


@router.patch("/sessions/{session_id}")
async def patch_session(
    services: ServicesDep, session_id: int, body: SessionPatch
) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if "note" in body.model_fields_set:
        updates["note"] = body.note or ""
    session = services.store.update_session(session_id, **updates)
    return public_session(session, recording_id=services.recorder.session_id)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(services: ServicesDep, session_id: int) -> Response:
    if services.recorder.session_id == session_id:
        raise ApiError(409, "session_recording", "Stop the recording before deleting it")
    services.store.delete_session(session_id)
    services.frames.clear()
    return Response(status_code=204)


@router.get("/sessions/{session_id}/analysis")
async def session_analysis(services: ServicesDep, session_id: int) -> dict[str, Any]:
    services.store.get_session(session_id)
    return await services.analysis.session(session_id)


@router.get("/laps/{lap_id}")
async def get_lap(services: ServicesDep, lap_id: int) -> dict[str, Any]:
    lap = public_lap(services.store.get_lap(lap_id))
    lap["metrics"] = None
    if services.analysis.available:
        try:
            result = await services.analysis.lap(lap_id)
        except Exception:
            log.exception("lap %s: analysis failed", lap_id)
        else:
            if isinstance(result, dict):
                lap["metrics"] = result.get("metrics")
    return lap


@router.get("/laps/{lap_id}/trace")
async def get_trace(
    services: ServicesDep, lap_id: int, hz: float = Query(20.0, gt=0, le=60)
) -> JSONResponse:
    lap = services.store.get_lap(lap_id)

    def build() -> dict[str, Any]:
        return build_trace(services.frames.get(lap), hz)

    return JSONResponse(await asyncio.to_thread(build))


@router.get("/laps/{lap_id}/analysis")
async def lap_analysis(services: ServicesDep, lap_id: int) -> dict[str, Any]:
    services.store.get_lap(lap_id)
    return await services.analysis.lap(lap_id)
