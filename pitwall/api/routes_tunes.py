"""Tune schema, immutable tune versions and the active tune."""

from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from pitwall.api.convert import public_tune
from pitwall.api.deps import ServicesDep
from pitwall.api.errors import ApiError
from pitwall.services.tunes import diff_values
from pitwall.storage.db import NotFound
from pitwall.tune.settings import BY_KEY, SETTINGS

router = APIRouter(prefix="/api")


class TuneCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    car_ordinal: int | None = None
    unit_system: Literal["imperial", "metric"]
    values: dict[str, float] = Field(default_factory=dict)
    parent_id: int | None = None
    note: str = ""


class ActiveTuneBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tune_id: int | None


@router.get("/tune-schema")
async def tune_schema() -> list[dict[str, Any]]:
    return [{**asdict(s), "drivetrains": list(s.drivetrains)} for s in SETTINGS]


@router.get("/tunes")
async def list_tunes(services: ServicesDep, car_ordinal: int | None = None) -> list[dict[str, Any]]:
    return [public_tune(t, with_values=False) for t in services.store.list_tunes(car_ordinal)]


@router.post("/tunes")
async def create_tune(services: ServicesDep, body: TuneCreate) -> dict[str, Any]:
    unknown = sorted(k for k in body.values if k not in BY_KEY)
    if unknown:
        raise ApiError(422, "unknown_setting", f"unknown setting(s): {', '.join(unknown)}")
    if any(not math.isfinite(v) for v in body.values.values()):
        raise ApiError(422, "validation_error", "values must be finite numbers")
    car_ordinal = body.car_ordinal
    changes: list[dict[str, Any]] = []
    if body.parent_id is not None:
        try:
            parent = services.store.get_tune(body.parent_id)
        except NotFound:
            raise ApiError(422, "unknown_parent", f"tune {body.parent_id} not found") from None
        changes = diff_values(parent["values"], body.values)
        if car_ordinal is None:
            car_ordinal = parent["car_ordinal"]
    tune = services.store.create_tune(
        name=body.name.strip(),
        car_ordinal=car_ordinal,
        unit_system=body.unit_system,
        values=body.values,
        parent_id=body.parent_id,
        changes=changes,
        note=body.note,
    )
    # A new version of the active tune becomes the active tune.
    if body.parent_id is not None and body.parent_id == services.active_tune_id:
        services.set_active_tune(tune["id"])
    return public_tune(tune)


@router.get("/tunes/active")
async def get_active_tune(services: ServicesDep) -> dict[str, Any] | None:
    if services.active_tune_id is None:
        return None
    try:
        return public_tune(services.store.get_tune(services.active_tune_id))
    except NotFound:
        return None


@router.put("/tunes/active")
async def put_active_tune(services: ServicesDep, body: ActiveTuneBody) -> dict[str, Any] | None:
    tune = None
    if body.tune_id is not None:
        tune = public_tune(services.store.get_tune(body.tune_id))
    services.set_active_tune(body.tune_id)
    return tune


@router.get("/tunes/{tune_id}")
async def get_tune(services: ServicesDep, tune_id: int) -> dict[str, Any]:
    return public_tune(services.store.get_tune(tune_id))
