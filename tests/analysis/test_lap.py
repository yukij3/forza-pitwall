from __future__ import annotations

import json
import time

import pytest

from pitwall.analysis import LapContext, analyze_lap
from pitwall.analysis.synthetic import SyntheticDriver

from .data import DRIVETRAIN_CODE, EXPECTED, EXPECTED_CHANGE, exists_for, lap_analyses, laps


def test_clean_lap_has_no_findings() -> None:
    for la in lap_analyses("none"):
        assert la.findings == ()
        assert la.recommendations == ()
        assert all(item.status in ("ok", "collecting") for item in la.items)


def test_clean_lap_metrics() -> None:
    la = lap_analyses("none")[1]
    m = la.metrics
    assert la.lap_number == 2  # 1-based like stored laps
    assert la.drivetrain == "RWD"
    assert m.corners == 8 and m.corners_slow == 5 and m.corners_fast == 3
    assert la.lap_time == pytest.approx(m.frames / 60, abs=0.1)
    assert 4000 < m.distance < 4300  # m
    assert 60 < m.max_speed < 85  # m/s, not km/h
    assert 0.3 < m.full_throttle_pct < 0.8 and 0.05 < m.braking_pct < 0.4
    assert all(abs(v) < 0.05 for v in m.balance.values() if v is not None)
    assert m.top_gear_used == 6 and m.limiter_time_s == 0
    assert m.end_of_straight_gear == 6 and 0.88 < (m.end_of_straight_rpm_pct or 0) < 0.97
    assert all(70 < t < 110 for t in m.tire_temp_avg.values())  # °C, not °F
    assert all(0 < w < 0.05 for w in m.tire_wear_delta.values())
    assert m.wheelspin_events == 0 and m.lockups == {"front": 0, "rear": 0}
    assert m.bottoming_events == 0
    assert [c.number for c in la.corners] == list(range(1, 9))


@pytest.mark.parametrize("issue", sorted(EXPECTED))
def test_injected_issue_gives_its_finding_and_change(issue: str) -> None:
    finding_id, _item = EXPECTED[issue]
    setting, direction = EXPECTED_CHANGE[(issue, "RWD")]
    for la in lap_analyses(issue)[1:]:
        assert la.findings, issue
        top = la.findings[0]
        assert top.id == finding_id
        assert top.severity >= 0.25 and top.confidence >= 0.4
        assert top.where, "findings say where they happen"
        rec = la.recommendations[0]
        assert (rec.finding_id, rec.setting, rec.direction) == (finding_id, setting, direction)


@pytest.mark.parametrize("issue", ["oversteer-exit", "wheelspin", "oversteer-entry", "lockup-rear"])
@pytest.mark.parametrize("drivetrain", ["FWD", "AWD"])
def test_drivetrain_specific_changes(issue: str, drivetrain: str) -> None:
    la = lap_analyses(issue, drivetrain)[1]
    setting, direction = EXPECTED_CHANGE[(issue, drivetrain)]
    assert (la.recommendations[0].setting, la.recommendations[0].direction) == (
        setting,
        direction,
    )
    assert all(exists_for(r.setting, drivetrain) for r in la.recommendations)


def test_where_points_at_the_slow_corners_for_wheelspin() -> None:
    la = lap_analyses("wheelspin")[1]
    finding = la.findings[0]
    slow = {c.number for c in la.corners if c.speed_band == "low"}
    assert {w.corner for w in finding.where} == slow


def test_to_dict_is_json_ready() -> None:
    la = lap_analyses("understeer")[1]
    data = json.loads(json.dumps(la.to_dict()))
    assert data["metrics"]["balance"]["mid"] > 0.2
    assert data["findings"][0]["id"] == "mid-understeer"
    assert data["recommendations"][0]["text"] == "Anti-roll Bars → Front: −2"
    assert {i["id"] for i in data["items"]} >= {"mid_balance_low", "gearing", "tire_temps"}
    assert data["lap_number"] == 2
    assert data["limits"]


def test_drivetrain_from_frames_when_context_has_none() -> None:
    la = analyze_lap(laps("wheelspin", "FWD")[1], LapContext())
    assert la.drivetrain == "FWD"
    assert la.recommendations[0].setting == "diff.accel_front"


def test_empty_and_tiny_inputs() -> None:
    empty = analyze_lap([], LapContext(drivetrain=1))
    assert empty.findings == () and empty.metrics.frames == 0
    json.dumps(empty.to_dict())
    tiny = analyze_lap(laps("none")[1][:5], LapContext(drivetrain=1))
    assert tiny.metrics.frames == 5 and tiny.findings == ()


def test_frames_with_race_off_are_ignored() -> None:
    from dataclasses import replace

    frames = list(laps("none")[1])
    paused = [replace(f, is_race_on=False) for f in frames[:600]]
    la = analyze_lap(paused + frames, LapContext(drivetrain=1))
    assert la.metrics.frames == len(frames)


def test_lap_context_values_are_used() -> None:
    frames = laps("oversteer-exit")[1]
    ctx = LapContext(
        drivetrain=DRIVETRAIN_CODE["RWD"],
        lap_kind="out",
        lap_valid=False,
        tune_values={"diff.accel_rear": 40.0},
        lap_time=91.5,
    )
    la = analyze_lap(frames, ctx)
    assert la.lap_kind == "out" and la.valid is False and la.lap_time == 91.5
    assert la.recommendations[0].suggested_value == 35.0


def test_two_minute_lap_analyzes_well_under_a_second() -> None:
    driver = SyntheticDriver("oversteer-exit", seed=2)
    frames = [f for _ in range(2) for f in driver.lap()][:7200]  # 120 s at 60 Hz
    start = time.perf_counter()
    la = analyze_lap(frames, LapContext(drivetrain=1))
    elapsed = time.perf_counter() - start
    assert la.metrics.frames == 7200
    assert elapsed < 0.5, f"{elapsed:.3f} s"
