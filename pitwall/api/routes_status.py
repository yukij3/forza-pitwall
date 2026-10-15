"""Status, recording control, settings and the live tuning board."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body
from pydantic import BaseModel, ConfigDict

from pitwall.api.convert import public_session
from pitwall.api.deps import ServicesDep

router = APIRouter(prefix="/api")


class StartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = None


class UnitsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    speed: Literal["kmh", "mph"] | None = None
    temperature: Literal["C", "F"] | None = None
    pressure: Literal["psi", "bar"] | None = None


class SettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    units: UnitsBody | None = None
    auto_record: bool | None = None


@router.get("/status")
async def get_status(services: ServicesDep) -> dict[str, Any]:
    return services.status()


@router.post("/recording/start")
async def start_recording(
    services: ServicesDep, body: Annotated[StartBody | None, Body()] = None
) -> dict[str, Any]:
    note = (body.note if body else None) or ""
    session = services.recorder.start(note.strip())
    return public_session(session, recording_id=services.recorder.session_id)


@router.post("/recording/stop")
async def stop_recording(services: ServicesDep) -> dict[str, Any]:
    session = services.recorder.stop()
    return public_session(session, recording_id=None)


@router.get("/settings")
async def get_settings(services: ServicesDep) -> dict[str, Any]:
    return services.store.get_settings()


@router.put("/settings")
async def put_settings(services: ServicesDep, body: SettingsBody) -> dict[str, Any]:
    settings = services.store.get_settings()
    if body.units is not None:
        settings["units"].update(body.units.model_dump(exclude_none=True))
    if body.auto_record is not None:
        settings["auto_record"] = body.auto_record
    saved = services.store.save_settings(settings)
    services.recorder.set_auto_record(bool(saved["auto_record"]))
    return saved


@router.get("/live-analysis")
async def get_live_analysis(services: ServicesDep) -> dict[str, Any]:
    return services.live_analysis.snapshot()


@router.post("/live-analysis/reset")
async def reset_live_analysis(services: ServicesDep) -> dict[str, Any]:
    services.live_analysis.module.require()
    return services.live_analysis.reset()
