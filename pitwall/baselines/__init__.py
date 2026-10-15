"""Baseline setups: approximate starting tunes per car category.

When a car is on track, ``match()`` finds its category and ``baseline()`` gives
starting values for every tuning-menu setting, so the live board has something
sensible to fine-tune from. Values are starting points, not optimal tunes; each
category cites its sources and states its confidence. See ``docs/baselines.md``.

    categories() -> list[Category]
    match(car_ordinal, car_pi, car_class, drivetrain) -> Match | None
    baseline(category_id, unit_system="imperial", drivetrain=None) -> Baseline
    car_info(car_ordinal) -> CarInfo | None

Pure functions over the bundled JSON data (read once, cached); no I/O beyond that.
"""

from __future__ import annotations

from .catalog import build_baseline, category_index, make_category
from .matching import car_info as _car_info
from .matching import drivetrain_name
from .matching import match as _match
from .types import Baseline, BaselineSetting, CarInfo, Category, Match, Source

__all__ = [
    "Baseline",
    "BaselineSetting",
    "CarInfo",
    "Category",
    "Match",
    "Source",
    "baseline",
    "car_info",
    "categories",
    "match",
]


def categories() -> list[Category]:
    """All categories, in display order."""
    return [make_category(raw) for raw in category_index().values()]


def match(
    car_ordinal: int | None,
    car_pi: int | None,
    car_class: int | None,
    drivetrain: int | str | None,
) -> Match | None:
    """Category for a car from its Data Out identity, or None if nothing is known.

    ``drivetrain`` is the Data Out integer (0 FWD, 1 RWD, 2 AWD) or the name.
    """
    return _match(car_ordinal, car_pi, car_class, drivetrain)


def baseline(
    category_id: str, unit_system: str = "imperial", drivetrain: int | str | None = None
) -> Baseline:
    """Starting values for a category, in the tune's unit system.

    ``drivetrain`` picks the differential settings (pass the car's drivetrain);
    by default the category's usual drivetrain is used. Raises ``KeyError`` for
    an unknown category and ``ValueError`` for an unknown unit system.
    """
    return build_baseline(category_id, unit_system, drivetrain_name(drivetrain))


def car_info(car_ordinal: int) -> CarInfo | None:
    """Name and division for a car ordinal, if the bundled car list knows it."""
    return _car_info(car_ordinal)
