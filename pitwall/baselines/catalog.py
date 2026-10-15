"""Load the baseline data files and build ``Baseline`` results from them.

``data/categories.json`` holds the categories, their per-setting starting values
(imperial units), sources and the class/drivetrain fallback table.
``data/cars.json`` (optional) maps car ordinals to name and division.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any

from pitwall.tune.settings import BY_KEY, SETTINGS

from .types import Baseline, BaselineSetting, CarInfo, Category, Source
from .units import check_unit_system, convert

DATA_DIR = Path(__file__).parent / "data"
DRIVETRAINS = ("FWD", "RWD", "AWD")
BASES = ("published", "carried_over", "principles")


@cache
def raw_categories() -> dict[str, Any]:
    with (DATA_DIR / "categories.json").open(encoding="utf-8") as fh:
        return json.load(fh)


@cache
def raw_cars() -> dict[str, Any]:
    path = DATA_DIR / "cars.json"
    if not path.exists():
        return {"cars": []}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


@cache
def category_index() -> dict[str, dict[str, Any]]:
    return {c["id"]: c for c in raw_categories()["categories"]}


@cache
def car_records() -> dict[int, dict[str, Any]]:
    return {int(c["ordinal"]): c for c in raw_cars()["cars"]}


def car_record(car_ordinal: int) -> dict[str, Any] | None:
    return car_records().get(car_ordinal)


def car_info_for(car_ordinal: int) -> CarInfo | None:
    rec = car_record(car_ordinal)
    if rec is None:
        return None
    return CarInfo(int(rec["ordinal"]), rec["name"], rec.get("division"))


def make_category(raw: Mapping[str, Any]) -> Category:
    return Category(
        id=raw["id"],
        name=raw["name"],
        description=raw["description"],
        divisions=tuple(raw["divisions"]),
        drivetrains=tuple(raw["drivetrains"]),
    )


def merged_settings(raw: Mapping[str, Any], drivetrain: str) -> dict[str, dict[str, Any]]:
    """Common defaults, then the category, each with its per-drivetrain layer on top."""
    common = raw_categories()["common"]
    merged: dict[str, dict[str, Any]] = {}
    for layer in (
        common.get("settings", {}),
        common.get("by_drivetrain", {}).get(drivetrain, {}),
        raw.get("settings", {}),
        raw.get("by_drivetrain", {}).get(drivetrain, {}),
    ):
        merged.update(layer)
    return {k: v for k, v in merged.items() if drivetrain in BY_KEY[k].drivetrains}


def _relative_text(entry: Mapping[str, Any]) -> str | None:
    pos = entry.get("position")
    if pos is None:
        return None
    text = f"≈{round(pos * 100)}% of slider"
    span = entry.get("position_range")
    if span:
        text += f" ({round(span[0] * 100)}–{round(span[1] * 100)}%)"
    return text


def make_setting(key: str, entry: Mapping[str, Any], unit_system: str) -> BaselineSetting:
    setting = BY_KEY[key]
    imperial_unit = setting.unit_imperial
    value = entry.get("value")
    span = entry.get("range")
    if value is not None:
        value = convert(float(value), imperial_unit, unit_system)
    if span is not None:
        span = (
            convert(float(span[0]), imperial_unit, unit_system),
            convert(float(span[1]), imperial_unit, unit_system),
        )
    return BaselineSetting(
        key=key,
        section=setting.section,
        label=setting.label,
        axle=setting.axle,
        value=value,
        range=span,
        unit=setting.unit_metric if unit_system == "metric" else imperial_unit,
        relative=_relative_text(entry),
        note=entry.get("note", ""),
        basis=entry.get("basis", "principles"),
    )


def build_baseline(category_id: str, unit_system: str, drivetrain: str | None) -> Baseline:
    check_unit_system(unit_system)
    try:
        raw = category_index()[category_id]
    except KeyError:
        raise KeyError(f"unknown baseline category {category_id!r}") from None
    category = make_category(raw)
    dt = drivetrain if drivetrain in DRIVETRAINS else category.drivetrains[0]
    entries = merged_settings(raw, dt)
    settings = tuple(
        make_setting(s.key, entries[s.key], unit_system) for s in SETTINGS if s.key in entries
    )
    common = raw_categories()["common"]
    notes = list(raw.get("notes", []))
    if dt not in category.drivetrains:
        notes.insert(
            0,
            f"Cars in this category normally aren't {dt}; the differential values are generic "
            f"{dt} starting points.",
        )
    notes.extend(common.get("notes", []))
    sources = tuple(
        Source(s["title"], s["url"], s.get("used_for", ""))
        for s in [*raw.get("sources", []), *common.get("sources", [])]
    )
    return Baseline(
        category=category,
        unit_system=unit_system,
        drivetrain=dt,
        settings=settings,
        notes=tuple(notes),
        sources=sources,
        confidence=raw["confidence"],
    )
