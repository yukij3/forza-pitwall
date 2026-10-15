from __future__ import annotations

import struct
from dataclasses import fields, replace

import pytest

from pitwall.telemetry import canonical
from pitwall.telemetry.model import Corners, Frame
from pitwall.telemetry.packet import (
    FM7_DASH_SIZE,
    FM2023_DASH_SIZE,
    NO_TRACK,
    SLED_SIZE,
    PacketError,
    blank_frame,
    canonical_gear,
    encode,
    parse,
    raw_gear,
)


def distinctive_frame() -> Frame:
    """Every field gets a different, float32-exact value."""
    values: dict[str, object] = {}
    n = 1
    for f in fields(Frame):
        if f.name in ("recv_time", "is_race_on"):
            continue
        if f.type == "Corners":
            if f.name == "wheel_on_rumble":
                values[f.name] = Corners(1, 0, 1, 0)
            else:
                values[f.name] = Corners(n + 0.25, n + 0.5, n + 0.75, n + 1.0)
        elif f.type == "float":
            values[f.name] = n + 0.5
        n += 1
    ints = {
        "timestamp_ms": 123456789,
        "car_ordinal": 3412,
        "car_class": 6,
        "car_pi": 812,
        "drivetrain": 1,
        "num_cylinders": 8,
        "lap_number": 513,
        "race_position": 3,
        "throttle": 255,
        "brake": 17,
        "clutch": 2,
        "handbrake": 1,
        "gear": 11,
        "steer": -100,
        "driving_line": 64,
        "ai_brake_diff": -5,
        "track_ordinal": 860,
    }
    return replace(blank_frame(), is_race_on=True, recv_time=42.0, **values, **ints)


def test_sizes() -> None:
    assert (SLED_SIZE, FM7_DASH_SIZE, FM2023_DASH_SIZE) == (232, 311, 331)


def test_round_trip() -> None:
    frame = distinctive_frame()
    data = encode(frame)
    assert len(data) == 331
    assert parse(data, 42.0) == frame


@pytest.mark.parametrize(
    ("offset", "fmt", "value"),
    [
        (0, "<i", 1),  # IsRaceOn
        (4, "<I", 123456789),  # TimestampMS
        (212, "<i", 3412),  # CarOrdinal
        (216, "<i", 6),  # CarClass
        (220, "<i", 812),  # CarPerformanceIndex
        (224, "<i", 1),  # DrivetrainType
        (228, "<i", 8),  # NumCylinders
        (300, "<H", 513),  # LapNumber
        (302, "<B", 3),  # RacePosition
        (303, "<B", 255),  # Accel
        (304, "<B", 17),  # Brake
        (305, "<B", 2),  # Clutch
        (306, "<B", 1),  # HandBrake
        (307, "<B", 11),  # Gear
        (308, "<b", -100),  # Steer
        (309, "<b", 64),  # NormalizedDrivingLine
        (310, "<b", -5),  # NormalizedAIBrakeDifference
        (327, "<i", 860),  # TrackOrdinal
    ],
)
def test_integer_offsets(offset: int, fmt: str, value: int) -> None:
    data = encode(distinctive_frame())
    assert struct.unpack_from(fmt, data, offset)[0] == value


@pytest.mark.parametrize(
    ("offset", "attr"),
    [
        (8, "engine_max_rpm"),
        (16, "current_engine_rpm"),
        (20, "accel_x"),
        (56, "yaw"),
        (232, "pos_x"),
        (244, "speed"),
        (280, "distance_traveled"),
        (284, "best_lap"),
        (288, "last_lap"),
        (292, "current_lap"),
        (296, "current_race_time"),
    ],
)
def test_float_offsets(offset: int, attr: str) -> None:
    frame = distinctive_frame()
    assert struct.unpack_from("<f", encode(frame), offset)[0] == getattr(frame, attr)


@pytest.mark.parametrize(
    ("offset", "attr"),
    [
        (68, "susp_travel_norm"),
        (84, "tire_slip_ratio"),
        (164, "tire_slip_angle"),
        (196, "susp_travel_m"),
        (256, "tire_temp"),
        (311, "tire_wear"),
    ],
)
def test_corner_offsets(offset: int, attr: str) -> None:
    frame = distinctive_frame()
    assert struct.unpack_from("<4f", encode(frame), offset) == tuple(getattr(frame, attr))


def test_fm7_packet() -> None:
    frame = distinctive_frame()
    data = encode(frame, fm7=True)
    assert len(data) == 311
    parsed = parse(data, 1.0)
    assert parsed.tire_wear == Corners(0.0, 0.0, 0.0, 0.0)
    assert parsed.track_ordinal == NO_TRACK
    assert parsed.speed == frame.speed and parsed.lap_number == frame.lap_number


@pytest.mark.parametrize("size", [0, 232, 310, 324, 330, 332])
def test_unsupported_sizes(size: int) -> None:
    with pytest.raises(PacketError):
        parse(bytes(size), 0.0)


def test_gear_encoding() -> None:
    assert [canonical_gear(g) for g in (0, 1, 6, 10, 11)] == [-1, 1, 6, 10, 0]
    assert [raw_gear(g) for g in (-1, 0, 1, 10)] == [0, 11, 1, 10]


def test_class_from_pi() -> None:
    cases = {0: None, 100: "E", 300: "E", 301: "D", 500: "C", 600: "B", 700: "A"}
    cases |= {800: "S", 812: "R", 998: "P", 999: "X"}
    assert {pi: canonical.class_name(pi) for pi in cases} == cases


def test_unit_conversions() -> None:
    assert canonical.f_to_c(212.0) == pytest.approx(100.0)
    assert canonical.pedal(255) == 1.0
    assert canonical.steer(-127) == -1.0
    assert canonical.steer(127) == 1.0
    frame = blank_frame(accel_x=9.81, accel_z=-19.62)
    assert canonical.lat_g(frame) == pytest.approx(1.0)
    assert canonical.lon_g(frame) == pytest.approx(-2.0)
