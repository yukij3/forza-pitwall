"""Setup reference data: the tune-setting schema and baseline setups."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter

from pitwall.api.deps import ServicesDep
from pitwall.tune.settings import SETTINGS

router = APIRouter(prefix="/api")

UnitSystem = Literal["imperial", "metric"]


@router.get("/tune-schema")
async def tune_schema() -> list[dict[str, Any]]:
    return [{**asdict(s), "drivetrains": list(s.drivetrains)} for s in SETTINGS]


@router.get("/baseline/categories")
async def baseline_categories(services: ServicesDep) -> list[Any]:
    return services.baselines.categories()


@router.get("/baseline")
async def baseline_for_car(
    services: ServicesDep, unit_system: UnitSystem | None = None
) -> dict[str, Any]:
    """Match for the car currently on track, and its baseline."""
    return services.baselines.for_car(
        services.receiver.last_race_frame, unit_system or services.unit_system()
    )


@router.get("/baseline/{category_id}")
async def baseline_for_category(
    services: ServicesDep, category_id: str, unit_system: UnitSystem | None = None
) -> dict[str, Any]:
    return services.baselines.baseline(category_id, unit_system or services.unit_system())
