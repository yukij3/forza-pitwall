"""Find the baseline category for the car on track.

Order: the car's ordinal (pinned category, or its in-game division) first, then
a guess from class, drivetrain and performance index. Data Out sends only the
ordinal, PI, class index and drivetrain; names and divisions come from
``data/cars.json`` when the ordinal is known.
"""

from __future__ import annotations

from typing import Any

from .catalog import DRIVETRAINS, car_info_for, car_record, category_index, raw_categories
from .types import CarInfo, Match

# FM2023 performance-index bands (same as pitwall.telemetry.canonical).
_CLASS_BANDS = (
    (300, "E"),
    (400, "D"),
    (500, "C"),
    (600, "B"),
    (700, "A"),
    (800, "S"),
    (900, "R"),
    (998, "P"),
    (999, "X"),
)
# FM2023 CarClass index as community tools observe it (the official page still
# lists the FM7 range). Used only when PI is missing.
_CLASS_BY_INDEX = ("E", "D", "C", "B", "A", "S", "R", "P", "X")


def drivetrain_name(value: int | str | None) -> str | None:
    if isinstance(value, str):
        value = value.upper()
        return value if value in DRIVETRAINS else None
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 3:
        return DRIVETRAINS[value]
    return None


def class_letter(car_pi: int | None, car_class: int | None) -> str | None:
    """Class from PI (reliable), else from the packet's class index."""
    if car_pi is not None and 100 <= car_pi <= 999:
        for upper, name in _CLASS_BANDS:
            if car_pi <= upper:
                return name
    if car_class is not None and 0 <= car_class < len(_CLASS_BY_INDEX):
        return _CLASS_BY_INDEX[car_class]
    return None


def car_info(car_ordinal: int | None) -> CarInfo | None:
    if car_ordinal is None or isinstance(car_ordinal, bool):
        return None
    return car_info_for(int(car_ordinal))


def by_division(division: str, drivetrain: str | None) -> tuple[str, str] | None:
    """Category for a division and drivetrain, as (category id, confidence).

    High when the drivetrain picks exactly the division's category; medium when
    the car runs a drivetrain swap its division doesn't have, or when the
    drivetrain is unknown and the division spans several categories.
    """
    candidates = [c for c in category_index().values() if division in c["divisions"]]
    if not candidates:
        return None
    if drivetrain:
        for cat in candidates:
            if drivetrain in cat["drivetrains"]:
                return cat["id"], "high"
        return candidates[0]["id"], "medium"
    return candidates[0]["id"], "high" if len(candidates) == 1 else "medium"


def by_class(letter: str, drivetrain: str) -> str | None:
    table: dict[str, Any] = raw_categories()["fallback"]
    return table.get(drivetrain, {}).get(letter)


def match(
    car_ordinal: int | None,
    car_pi: int | None,
    car_class: int | None,
    drivetrain: int | str | None,
) -> Match | None:
    dt = drivetrain_name(drivetrain)
    info = car_info(car_ordinal)
    if info is not None:
        pinned = (car_record(info.ordinal) or {}).get("category")
        if pinned and pinned in category_index():
            return Match(pinned, "ordinal", "high", info)
        if info.division:
            found = by_division(info.division, dt)
            if found:
                return Match(found[0], "division", found[1], info)
    letter = class_letter(car_pi, car_class)
    if letter is None:
        return None
    cat_id = by_class(letter, dt or "RWD")
    if cat_id is None:
        return None
    return Match(cat_id, "class_drivetrain", "low", info)
