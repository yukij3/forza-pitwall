from __future__ import annotations

import itertools
import math

import pytest

from pitwall.analysis.synthetic import (
    ISSUES,
    SyntheticDriver,
    generate_lap,
    generate_laps,
    track,
)
from pitwall.telemetry.model import Frame

from .data import laps


def test_track_is_a_closed_loop() -> None:
    trk = track()
    assert 3500 < trk.length < 5500
    assert math.isclose(trk.x[0], trk.x[-1], abs_tol=1e-6)
    assert math.isclose(trk.z[0], trk.z[-1], abs_tol=1e-6)
    assert math.isclose(trk.heading[-1] - trk.heading[0], 2 * math.pi, abs_tol=1e-6)


def test_same_seed_gives_identical_frames() -> None:
    a = generate_lap("oversteer-exit", seed=4)
    b = generate_lap("oversteer-exit", seed=4)
    assert a == b


def test_different_seeds_differ() -> None:
    a = generate_lap("none", seed=1)
    b = generate_lap("none", seed=2)
    assert a != b


def test_laps_are_one_continuous_stint() -> None:
    first, second, _ = laps("none")
    assert first[0].lap_number == 0 and second[0].lap_number == 1
    assert second[0].last_lap == pytest.approx(first[-1].current_lap, abs=0.05)
    assert second[0].current_lap < 0.05
    gap_ms = (second[0].timestamp_ms - first[-1].timestamp_ms) % (1 << 32)
    assert gap_ms in (16, 17)
    assert second[0].distance_traveled > first[-1].distance_traveled
    assert all(f.is_race_on for f in first)


def test_lap_looks_like_data_out() -> None:
    frames = laps("none")[1]
    lap_time = frames[-1].current_lap
    assert 70 < lap_time < 100
    assert len(frames) == pytest.approx(lap_time * 60, abs=2)
    assert max(f.speed for f in frames) > 60  # m/s
    temps = [t for f in frames for t in f.tire_temp]
    assert min(temps) > 150 and max(temps) < 230  # °F, like the game
    assert {f.gear for f in frames} <= set(range(1, 7))
    assert all(-127 <= f.steer <= 127 and 0 <= f.throttle <= 255 for f in frames)
    assert all(0.0 <= x <= 1.0 for f in frames for x in f.susp_travel_norm)


@pytest.mark.parametrize("drivetrain,code", [("FWD", 0), ("RWD", 1), ("AWD", 2)])
def test_drivetrain_is_encoded_like_data_out(drivetrain: str, code: int) -> None:
    frame = generate_laps("none", 1, drivetrain=drivetrain)[0][0]
    assert frame.drivetrain == code


def test_stream_is_endless_and_continuous() -> None:
    driver = SyntheticDriver("wheelspin", drivetrain="AWD", seed=3, hz=30)
    frames: list[Frame] = list(itertools.islice(driver.frames(), 4000))
    assert {f.lap_number for f in frames} == {0, 1}
    steps = {
        round(b.current_race_time - a.current_race_time, 6) for a, b in itertools.pairwise(frames)
    }
    assert steps == {round(1 / 30, 6)}


def test_issue_combinations_and_validation() -> None:
    assert generate_lap(["wheelspin", "lockup-rear"], seed=1)
    with pytest.raises(ValueError):
        SyntheticDriver("flat-tire")
    with pytest.raises(ValueError):
        SyntheticDriver("none", drivetrain="4WD")
    assert "none" in ISSUES and len(ISSUES) == len(set(ISSUES))
