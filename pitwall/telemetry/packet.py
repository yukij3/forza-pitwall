"""Parse and encode Forza Motorsport "Data Out" packets.

Layout (little-endian, no padding), verified against the official
Forza Motorsport (2023) Data Out documentation:

* Sled section, 232 bytes (offsets 0..231)
* Dash section, 79 bytes (offsets 232..310); together these are the
  Forza Motorsport 7 "Car Dash" packet (311 bytes)
* Forza Motorsport (2023) additions, 20 bytes (offsets 311..330):
  ``TireWear`` x4 (f32) and ``TrackOrdinal`` (s32); total 331 bytes

See ``docs/data-out.md`` for the full field table.
"""

from __future__ import annotations

import struct
from dataclasses import fields, replace
from typing import Any

from pitwall.telemetry.model import Corners, Frame

SLED_FORMAT = "<iI" + "f" * 15 + "f" * 12 + "i" * 4 + "f" * 20 + "i" * 5
DASH_FORMAT = "f" * 17 + "H" + "B" * 6 + "b" * 3
FM2023_FORMAT = "f" * 4 + "i"

_FM7_STRUCT = struct.Struct(SLED_FORMAT + DASH_FORMAT)
_FM2023_STRUCT = struct.Struct(SLED_FORMAT + DASH_FORMAT + FM2023_FORMAT)

SLED_SIZE = struct.calcsize(SLED_FORMAT)  # 232
FM7_DASH_SIZE = _FM7_STRUCT.size  # 311
FM2023_DASH_SIZE = _FM2023_STRUCT.size  # 331
SUPPORTED_SIZES = (FM2023_DASH_SIZE, FM7_DASH_SIZE)

# Gear byte: 0 = reverse, 1..10 = forward gears, 11 = neutral. Not in the official
# doc; this is the encoding observed by community tools for FM7/FM2023/FH.
RAW_GEAR_REVERSE = 0
RAW_GEAR_NEUTRAL = 11

# FM2023 track_ordinal is absent from FM7 packets; parse() fills in this value.
NO_TRACK = -1

_CORNER_FIELDS = (
    "susp_travel_norm",
    "tire_slip_ratio",
    "wheel_rot_speed",
    "wheel_on_rumble",
    "wheel_in_puddle",
    "surface_rumble",
    "tire_slip_angle",
    "tire_combined_slip",
    "susp_travel_m",
)
_SCALAR_HEAD = (
    "is_race_on",
    "timestamp_ms",
    "engine_max_rpm",
    "engine_idle_rpm",
    "current_engine_rpm",
    "accel_x",
    "accel_y",
    "accel_z",
    "vel_x",
    "vel_y",
    "vel_z",
    "ang_vel_x",
    "ang_vel_y",
    "ang_vel_z",
    "yaw",
    "pitch",
    "roll",
)
_SLED_TAIL = ("car_ordinal", "car_class", "car_pi", "drivetrain", "num_cylinders")
_DASH_HEAD = ("pos_x", "pos_y", "pos_z", "speed", "power", "torque")
_DASH_MID = (
    "boost",
    "fuel",
    "distance_traveled",
    "best_lap",
    "last_lap",
    "current_lap",
    "current_race_time",
    "lap_number",
    "race_position",
    "throttle",
    "brake",
    "clutch",
    "handbrake",
    "gear",
    "steer",
    "driving_line",
    "ai_brake_diff",
)
_INT_CORNERS = frozenset({"wheel_on_rumble"})


class PacketError(ValueError):
    """Raised for datagrams that are not a supported Car Dash packet."""


def parse(data: bytes, recv_time: float) -> Frame:
    """Decode one Car Dash datagram (331 bytes FM2023, or 311 bytes FM7)."""
    size = len(data)
    if size == FM2023_DASH_SIZE:
        values = _FM2023_STRUCT.unpack(data)
    elif size == FM7_DASH_SIZE:
        values = _FM7_STRUCT.unpack(data) + (0.0, 0.0, 0.0, 0.0, NO_TRACK)
    else:
        raise PacketError(f"unsupported packet size {size}")

    it = iter(values)
    out: dict[str, Any] = {"recv_time": recv_time}
    for name in _SCALAR_HEAD:
        out[name] = next(it)
    for name in _CORNER_FIELDS:
        out[name] = Corners(next(it), next(it), next(it), next(it))
    for name in _SLED_TAIL:
        out[name] = next(it)
    for name in _DASH_HEAD:
        out[name] = next(it)
    out["tire_temp"] = Corners(next(it), next(it), next(it), next(it))
    for name in _DASH_MID:
        out[name] = next(it)
    out["tire_wear"] = Corners(next(it), next(it), next(it), next(it))
    out["track_ordinal"] = next(it)
    out["is_race_on"] = out["is_race_on"] != 0
    return Frame(**out)


def encode(frame: Frame, *, fm7: bool = False) -> bytes:
    """Encode a frame as a 331-byte FM2023 packet (or 311-byte FM7 with ``fm7``)."""
    values: list[Any] = [1 if frame.is_race_on else 0, int(frame.timestamp_ms) & 0xFFFFFFFF]
    values += [getattr(frame, name) for name in _SCALAR_HEAD[2:]]
    for name in _CORNER_FIELDS:
        corners = getattr(frame, name)
        if name in _INT_CORNERS:
            values += [int(round(v)) for v in corners]
        else:
            values += list(corners)
    values += [int(getattr(frame, name)) for name in _SLED_TAIL]
    values += [getattr(frame, name) for name in _DASH_HEAD]
    values += list(frame.tire_temp)
    values += [getattr(frame, name) for name in _DASH_MID[:7]]
    values += [int(getattr(frame, name)) for name in _DASH_MID[7:]]
    if fm7:
        return _FM7_STRUCT.pack(*values)
    values += list(frame.tire_wear)
    values.append(int(frame.track_ordinal))
    return _FM2023_STRUCT.pack(*values)


_ZERO = Corners(0.0, 0.0, 0.0, 0.0)


def blank_frame(**overrides: Any) -> Frame:
    """A frame with every field zeroed (race off), with optional overrides.

    Useful for "in menus" packets, tests and synthetic data.
    """
    base: dict[str, Any] = {}
    for f in fields(Frame):
        if f.name == "is_race_on":
            base[f.name] = False
        elif f.type in ("Corners", Corners):
            base[f.name] = _ZERO
        elif f.type in ("float", float):
            base[f.name] = 0.0
        else:
            base[f.name] = 0
    base["track_ordinal"] = NO_TRACK
    frame = Frame(**base)
    return replace(frame, **overrides) if overrides else frame


def canonical_gear(raw_gear: int) -> int:
    """Map the raw gear byte to -1 = reverse, 0 = neutral, 1..10 = forward."""
    if raw_gear == RAW_GEAR_REVERSE:
        return -1
    if raw_gear >= RAW_GEAR_NEUTRAL:
        return 0
    return raw_gear


def raw_gear(gear: int) -> int:
    """Inverse of :func:`canonical_gear`."""
    if gear < 0:
        return RAW_GEAR_REVERSE
    if gear == 0:
        return RAW_GEAR_NEUTRAL
    return gear
