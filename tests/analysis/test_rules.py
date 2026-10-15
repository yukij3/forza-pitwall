"""Rulebook, wording, step maths, band scores and hysteresis."""

from __future__ import annotations

import pytest

from pitwall.analysis.assess import Evidence, assess_all, band_score, status_for
from pitwall.analysis.records import BrakeRecord, CornerRecord, PhaseStats
from pitwall.analysis.rules import (
    RULES,
    STEPS,
    applicable_changes,
    build_recommendation,
    change_text,
    describe_change,
    suggested_value,
)
from pitwall.analysis.thresholds import BANDS
from pitwall.tune.settings import BY_KEY

M = "−"
A = "→"


@pytest.mark.parametrize(
    "key,direction,unit_system,text",
    [
        ("diff.accel_rear", -1, "imperial", f"Differential {A} Acceleration (Rear): {M}5%"),
        ("arb.front", -1, "imperial", f"Anti-roll Bars {A} Front: {M}2"),
        ("springs.ride_height_front", 1, "metric", f"Springs {A} Ride Height (Front): +0.5 cm"),
        ("springs.ride_height_rear", 1, "imperial", f"Springs {A} Ride Height (Rear): +0.2 in"),
        ("springs.front", 1, "imperial", f"Springs {A} Front: +50 lb/in"),
        ("springs.front", 1, "metric", f"Springs {A} Front: +1.0 kgf/mm"),
        ("aero.rear", 1, "metric", f"Aero {A} Downforce (Rear): +5 kgf"),
        ("brake.balance", 1, "imperial", f"Brake {A} Braking Balance: +1% (more front)"),
        ("brake.balance", -1, "imperial", f"Brake {A} Braking Balance: {M}1% (more rear)"),
        ("brake.pressure", -1, "imperial", f"Brake {A} Braking Pressure: {M}5%"),
        ("gearing.final_drive", -1, "imperial", f"Gearing {A} Final Drive: {M}0.10 (longer)"),
        ("gearing.final_drive", 1, "imperial", f"Gearing {A} Final Drive: +0.10 (shorter)"),
        ("diff.center_balance", 1, "imperial", f"Differential {A} Center Balance: +5% (more rear)"),
        ("tires.pressure_front", 1, "imperial", f"Tires {A} Tire Pressure (Front): +0.5 psi"),
        ("tires.pressure_front", 1, "metric", f"Tires {A} Tire Pressure (Front): +0.03 bar"),
    ],
)
def test_menu_wording(key: str, direction: int, unit_system: str, text: str) -> None:
    step = STEPS[key].size(unit_system)
    assert change_text(BY_KEY[key], direction, step, unit_system) == text


def test_every_rule_points_at_a_real_setting_with_a_step() -> None:
    for fid, changes in RULES.items():
        assert changes, fid
        for ch in changes:
            assert ch.setting in BY_KEY, (fid, ch.setting)
            assert ch.setting in STEPS
            assert ch.direction in (1, -1) and 0 < ch.prior <= 1


def test_suggested_value_math() -> None:
    assert suggested_value("diff.accel_rear", 40.0, -1, 5.0) == 35.0
    assert suggested_value("diff.accel_rear", 3.0, -1, 5.0) == 0.0  # clamped to the range
    assert suggested_value("arb.front", 64.5, 1, 2.0) == 65.0
    assert suggested_value("brake.balance", 52.0, 1, 1.0) == 53.0
    assert suggested_value("gearing.final_drive", 3.85, -1, 0.1) == 3.75
    assert suggested_value("springs.ride_height_front", 5.1, 1, 0.2) == 5.3
    assert suggested_value("arb.front", None, -1, 2.0) is None


def test_recommendation_fills_suggested_value_only_from_tune_values() -> None:
    ch = RULES["mid-understeer"][0]
    common = dict(finding_id="mid-understeer", reason="r", confidence=0.8, unit_system="imperial")
    with_value = build_recommendation(ch, tune_values={"arb.front": 20.0}, **common)
    without = build_recommendation(ch, tune_values={"arb.rear": 20.0}, **common)
    assert with_value.suggested_value == 18.0 and without.suggested_value is None
    assert with_value.id == "arb-front-down" and with_value.step == 2.0


def test_drivetrain_filtering_in_candidates() -> None:
    def settings(fid: str, dt: str, axle: str | None = None) -> list[str]:
        return [c.setting for c, _ in applicable_changes(fid, dt, axle, {})]

    assert settings("exit-oversteer", "FWD")[0] == "arb.rear"
    assert "diff.accel_rear" not in settings("exit-oversteer", "FWD")
    assert "diff.center_balance" not in settings("exit-oversteer", "RWD")
    assert settings("exit-oversteer", "AWD")[:1] == ["diff.accel_rear"]
    assert settings("exit-wheelspin", "FWD", "front")[0] == "diff.accel_front"
    assert settings("exit-wheelspin", "AWD", "rear")[:2] == [
        "diff.accel_rear",
        "diff.center_balance",
    ]
    assert settings("entry-understeer", "FWD")[0] == "diff.decel_front"
    assert settings("exit-understeer", "AWD")[0] == "diff.center_balance"
    for dt in ("FWD", "RWD", "AWD"):
        for fid in RULES:
            for axle in (None, "front", "rear"):
                assert all(dt in BY_KEY[s].drivetrains for s in settings(fid, dt, axle))


def test_describe_change() -> None:
    assert describe_change("arb.front", 20.0, 18.5) == f"Anti-roll Bars {A} Front: 20 {A} 18.5"
    assert describe_change("unknown.key", None, None) == "unknown.key: changed"


def test_band_score() -> None:
    b = BANDS["mid_balance_low"]  # ok -0.05..+0.10, bad beyond -0.20 / +0.25
    assert band_score(0.10, b) == 0.0
    assert band_score(0.25, b) == pytest.approx(0.5)
    assert band_score(-0.20, b) == pytest.approx(0.5)
    assert band_score(0.02, b) < 0
    assert band_score(5.0, b) == 1.0
    rate = BANDS["lockups_rear"]
    assert band_score(0.0, rate) < 0 and band_score(0.25, rate) == pytest.approx(0.5)


class _A:
    """Minimal stand-in for an Assessment in status_for()."""

    def __init__(self, score: float, collecting: bool = False) -> None:
        self.score = score
        self.collecting = collecting


@pytest.mark.parametrize(
    "previous,score,expected",
    [
        (None, 0.05, "warn"),
        ("ok", 0.05, "ok"),  # inside the hysteresis margin: no flip
        ("ok", 0.15, "warn"),
        ("ok", 0.65, "bad"),
        ("warn", -0.05, "warn"),
        ("warn", -0.15, "ok"),
        ("warn", 0.55, "warn"),
        ("bad", 0.45, "bad"),
        ("bad", 0.35, "warn"),
        ("bad", -0.2, "ok"),
        ("collecting", 0.3, "warn"),
    ],
)
def test_status_hysteresis(previous: str | None, score: float, expected: str) -> None:
    assert status_for(_A(score), previous) == expected  # type: ignore[arg-type]


def test_collecting_until_enough_samples() -> None:
    assert status_for(_A(0.9, collecting=True), "bad") == "collecting"  # type: ignore[arg-type]


def _corner(n: int, balance: float, oversteer_s: float = 0.0) -> CornerRecord:
    phase = PhaseStats(samples=20, balance=balance, slip=balance, yaw=balance)
    mid = PhaseStats(samples=20, balance=balance, oversteer_s=oversteer_s)
    return CornerRecord(
        sign=1, t_start=n * 10.0, t_end=n * 10.0 + 3, start_dist=n * 300.0,
        apex_dist=n * 300.0 + 50, end_dist=n * 300.0 + 100, entry_speed=40, min_speed=20,
        exit_speed=35, peak_lat_g=1.3, heading_deg=90, band="low", entry=phase, mid=mid,
        exit=phase, number=n,
    )  # fmt: skip


def _brake(n: int, rear_lock: float = 0.0) -> BrakeRecord:
    return BrakeRecord(
        t_start=n * 10.0, start_dist=n * 300.0 - 100, end_dist=n * 300.0, entry_speed=60,
        exit_speed=20, duration=2.5, peak_decel_g=1.4, lock_rear_s=rear_lock,
    )  # fmt: skip


def _evidence(corners: list[CornerRecord], brakes: list[BrakeRecord]) -> Evidence:
    return Evidence(corners, brakes, [], [], None, 0.0, 6, "RWD")


def test_a_single_mistake_does_not_flag_an_item() -> None:
    corners = [_corner(n, 0.02) for n in range(1, 12)] + [_corner(12, -0.9, oversteer_s=0.8)]
    brakes = [_brake(n) for n in range(1, 12)] + [_brake(12, rear_lock=0.5)]
    by_id = {a.item: a for a in assess_all(_evidence(corners, brakes))}
    assert status_for(by_id["mid_balance_low"]) == "ok"
    assert status_for(by_id["lockups_rear"]) == "ok"
    # ... but a habit does
    brakes = [_brake(n, rear_lock=0.5 if n % 3 == 0 else 0.0) for n in range(1, 13)]
    by_id = {a.item: a for a in assess_all(_evidence(corners, brakes))}
    assert status_for(by_id["lockups_rear"]) in ("warn", "bad")
    assert by_id["lockups_rear"].finding_id == "lockup-rear"


def test_both_axles_locking_means_too_much_pressure() -> None:
    brakes = [
        BrakeRecord(
            t_start=n, start_dist=n * 300.0, end_dist=n * 300.0 + 80, entry_speed=60,
            exit_speed=20, duration=2.0, peak_decel_g=1.4, lock_front_s=0.3, lock_rear_s=0.3,
        )
        for n in range(8)
    ]  # fmt: skip
    by_id = {a.item: a for a in assess_all(_evidence([], brakes))}
    assert by_id["lockups_front"].finding_id == "lockup-both"
    assert by_id["lockups_rear"].finding_id == "lockup-both"
    assert RULES["lockup-both"][0].setting == "brake.pressure"
