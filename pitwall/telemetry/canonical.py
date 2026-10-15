"""Conversions from raw game units to the API's canonical units.

Frames keep raw game units; everything that leaves the API goes through here:
speed m/s, temperature degC, distance m, time s, pedals 0..1, steer -1..1,
accelerations in g.
"""

from __future__ import annotations

from pitwall.telemetry.model import Corners, Drivetrain, Frame
from pitwall.telemetry.packet import NO_TRACK, canonical_gear

G = 9.81

DRIVETRAIN_NAMES = {Drivetrain.FWD: "FWD", Drivetrain.RWD: "RWD", Drivetrain.AWD: "AWD"}

# Forza Motorsport (2023) performance-index bands. The CarClass index in the
# packet is 0 = E .. 8 = X in FM2023 (the official doc still describes the FM7
# range 0 = D .. 7 = X), so the class letter is derived from PI instead.
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


def f_to_c(fahrenheit: float) -> float:
    return (fahrenheit - 32.0) * 5.0 / 9.0


def pedal(raw: int) -> float:
    return raw / 255.0


def steer(raw: int) -> float:
    return max(-1.0, min(1.0, raw / 127.0))


def lat_g(frame: Frame) -> float:
    return frame.accel_x / G


def lon_g(frame: Frame) -> float:
    return frame.accel_z / G


def drivetrain_name(value: int) -> str | None:
    return DRIVETRAIN_NAMES.get(value)


def class_name(pi: int) -> str | None:
    """Class letter for a performance index (FM2023 bands), or None if unknown."""
    if pi < 100:
        return None
    for upper, name in _CLASS_BANDS:
        if pi <= upper:
            return name
    return None


def track_ordinal(value: int) -> int | None:
    return None if value == NO_TRACK else value


def lap_time(value: float) -> float | None:
    """The game reports 0 for "no time yet"."""
    return value if value > 0 else None


def corners(values: Corners, digits: int = 4) -> dict[str, float]:
    return {
        "fl": round(values.fl, digits),
        "fr": round(values.fr, digits),
        "rl": round(values.rl, digits),
        "rr": round(values.rr, digits),
    }


def corners_c(values: Corners) -> dict[str, float]:
    return {k: round(f_to_c(v), 2) for k, v in zip(("fl", "fr", "rl", "rr"), values, strict=True)}


def gear(raw: int) -> int:
    return canonical_gear(raw)
