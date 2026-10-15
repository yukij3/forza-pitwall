"""Behaviour calibrated on real PC recordings: packet rate, clocks, ABS, rewinds, gamepads."""

from __future__ import annotations

import math
import time
from dataclasses import replace
from functools import cache

import pytest

from pitwall.analysis import LapAnalysis, LapContext, LiveAnalyzer, analyze_lap
from pitwall.analysis.samples import SampleBuilder
from pitwall.analysis.synthetic import generate_laps
from pitwall.analysis.yaw import YawFit
from pitwall.telemetry.model import Frame

from .data import EXPECTED, laps

RWD = 1
BUDGET_160HZ_S = 1 / 160


@cache
def fast_laps(issue: str, hz: float) -> tuple[tuple[Frame, ...], ...]:
    return tuple(tuple(lap) for lap in generate_laps(issue, 2, hz=hz, seed=11))


def analyse(frames) -> LapAnalysis:  # type: ignore[no-untyped-def]
    return analyze_lap(list(frames), LapContext(drivetrain=RWD))


def found(la: LapAnalysis) -> set[str]:
    return {f.id for f in la.findings}


def samples(frames) -> list:  # type: ignore[no-untyped-def]
    b = SampleBuilder()
    out = []
    for f in frames:
        out.extend(b.push(f))
    out.extend(b.flush())
    return out


# --- Time base -----------------------------------------------------------------------------
@pytest.mark.parametrize("hz", [144, 165])
def test_time_base_survives_repeated_timestamps(hz: int) -> None:
    lap = fast_laps("none", hz)[1]
    stamps = [f.timestamp_ms for f in lap]
    repeated = sum(1 for a, b in zip(stamps, stamps[1:], strict=False) if a == b) / len(lap)
    assert repeated > 0.4  # TimestampMS ticks at ~64 Hz, like the PC game
    ref = analyse(laps("none")[1]).metrics
    m = analyse(lap).metrics
    assert m.sample_rate_hz == pytest.approx(hz, rel=0.01)
    span = lap[-1].current_race_time - lap[0].current_race_time
    assert sum(s.dt for s in samples(lap)) == pytest.approx(span, abs=0.05)
    assert m.distance == pytest.approx(ref.distance, rel=0.01)
    assert m.lap_time == pytest.approx(ref.lap_time, abs=0.05)


def test_time_base_falls_back_without_double_counting() -> None:
    lap = fast_laps("none", 144)[1]
    race_span = lap[-1].current_race_time - lap[0].current_race_time

    def total(frames) -> float:  # type: ignore[no-untyped-def]
        return sum(s.dt for s in samples(frames))

    no_race = [replace(f, current_race_time=0.0) for f in lap]  # lap timer only
    assert total(no_race) == pytest.approx(race_span, abs=0.05)
    no_timers = [replace(f, current_lap=0.0) for f in no_race]  # receive time
    assert total(no_timers) == pytest.approx(lap[-1].recv_time - lap[0].recv_time, abs=0.05)
    stamps_only = [replace(f, recv_time=0.0) for f in no_timers]  # repeated stamps = 0 s
    ts_span = (lap[-1].timestamp_ms - lap[0].timestamp_ms) / 1000
    assert total(stamps_only) == pytest.approx(ts_span, abs=0.05)


# --- Packet rate ---------------------------------------------------------------------------
@pytest.mark.parametrize("hz", [144, 165])
@pytest.mark.parametrize(
    "issue", ["understeer", "oversteer-exit", "wheelspin", "lockup-front", "bottoming"]
)
def test_same_findings_at_pc_packet_rates(issue: str, hz: int) -> None:
    finding, _ = EXPECTED[issue]
    assert finding in found(analyse(fast_laps(issue, hz)[1]))


@pytest.mark.parametrize("hz", [144, 165])
def test_clean_lap_stays_clean_at_pc_packet_rates(hz: int) -> None:
    assert found(analyse(fast_laps("none", hz)[1])) == set()


def test_live_board_at_160hz_turns_within_two_laps_and_fits_the_frame_budget() -> None:
    frames = [f for lap in fast_laps("lockup-front", 160) for f in lap]
    live = LiveAnalyzer(RWD)
    costs = []
    for frame in frames:
        t0 = time.perf_counter()
        live.push(frame)
        costs.append(time.perf_counter() - t0)
    assert live.snapshot().item("lockups_front").status in ("warn", "bad")
    costs.sort()
    assert sum(costs) / len(costs) < 0.0001
    assert costs[int(len(costs) * 0.999)] < BUDGET_160HZ_S
    assert costs[-1] < 0.03


# --- Lockups under ABS -----------------------------------------------------------------------
def _old_rule_hits(lap) -> int:  # type: ignore[no-untyped-def]
    """Braking runs the old "front slip ratio <= -1 for >= 0.08 s" rule would call lockups."""
    hits, run = 0, 0.0
    for a, b in zip(lap, lap[1:], strict=False):
        if min(b.tire_slip_ratio[0], b.tire_slip_ratio[1]) <= -1.0 and b.brake > 25:
            run += b.current_race_time - a.current_race_time
        else:
            hits += run >= 0.08
            run = 0.0
    return hits


def test_abs_modulation_is_not_a_lockup() -> None:
    lap = fast_laps("none", 144)[1]
    assert _old_rule_hits(lap) >= 5  # deep ABS dips, as recorded with ABS on
    m = analyse(lap).metrics
    assert m.lockups == {"front": 0, "rear": 0}


def test_lock_is_caught_by_wheel_speed_when_slip_ratio_lags() -> None:
    # the game's slip ratio can sit near -1.3 while the wheel has already stopped
    lap = [
        replace(f, tire_slip_ratio=(-1.29, -1.29, *f.tire_slip_ratio[2:]))
        if f.tire_slip_ratio[0] < -5.0
        else f
        for f in fast_laps("lockup-front", 144)[1]
    ]
    assert "lockup-front" in found(analyse(lap))


def test_lock_is_caught_before_the_wheel_radius_is_known() -> None:
    # no wheel speeds at all: only a slip ratio deep enough to mean a stopped wheel counts
    still = (0.0, 0.0, 0.0, 0.0)
    lap = [replace(f, wheel_rot_speed=still) for f in fast_laps("lockup-front", 144)[1]]
    assert "lockup-front" in found(analyse(lap))
    clean = [replace(f, wheel_rot_speed=still) for f in fast_laps("none", 144)[1]]
    assert analyse(clean).metrics.lockups == {"front": 0, "rear": 0}


def test_wheel_in_the_air_is_not_a_lock() -> None:
    lap = [
        replace(f, susp_travel_norm=(0.0, 0.0, *f.susp_travel_norm[2:]))
        if f.tire_slip_ratio[0] < -5.0
        else f
        for f in fast_laps("lockup-front", 144)[1]
    ]
    assert analyse(lap).metrics.lockups["front"] == 0


# --- Rewinds ---------------------------------------------------------------------------------
def _rewind(frames: list[Frame], at: int, back_s: float, pause_s: float = 6.0) -> list[Frame]:
    """At frame ``at`` the game rewinds ``back_s`` seconds after a ``pause_s`` menu."""
    t_at = frames[at].current_race_time
    j = next(i for i, f in enumerate(frames) if f.current_race_time >= t_at - back_s)
    shift = frames[at - 1].recv_time + pause_s - frames[j].recv_time
    tail = [
        replace(
            f,
            recv_time=f.recv_time + shift,
            timestamp_ms=(f.timestamp_ms + round(shift * 1000)) & 0xFFFFFFFF,
        )
        for f in frames[j:]
    ]
    return frames[:at] + tail


def _corner_records(frames: list[Frame]) -> list:  # type: ignore[no-untyped-def]
    live = LiveAnalyzer(RWD, window_corners=1000)
    for f in frames:
        live.push(f)
    return list(live._corners)


def test_rewind_never_produces_a_corner_across_it() -> None:
    lap = list(fast_laps("none", 144)[1])
    clean = _corner_records(lap)
    # rewind from mid-corner to 1 s before that corner started (on a straight)
    t0 = lap[0].current_race_time
    gaps = [(b.t_start - a.t_end, b) for a, b in zip(clean, clean[1:], strict=False)]
    _, corner = max(gaps, key=lambda g: g[0])
    mid = (corner.t_start + corner.t_end) / 2
    at = next(i for i, f in enumerate(lap) if f.current_race_time - t0 >= mid)
    spliced = _rewind(lap, at, back_s=mid - corner.t_start + 1.0)

    ss = samples(spliced)
    cuts = [s for s in ss if s.cut]
    assert len(cuts) == 1
    cut = cuts[0]
    assert cut.dt < 0.01  # the menu pause adds no time
    before = ss[ss.index(cut) - 1]
    assert cut.dist < before.dist - 10  # distance follows the car back

    recs = _corner_records(spliced)
    assert len(recs) == len(clean)
    assert not any(r.t_start < cut.t <= r.t_end for r in recs)
    assert analyse(spliced).metrics.corners == analyse(lap).metrics.corners


def test_rewind_is_found_from_the_lap_timer_without_a_race_clock() -> None:
    lap = [replace(f, current_race_time=0.0) for f in fast_laps("none", 144)[1]]
    spliced = lap[:4000] + lap[3300:5000]  # the lap timer steps back ~4.9 s
    ss = samples(spliced)
    assert sum(1 for s in ss if s.cut) == 1


def test_restart_resets_without_smoothing_across_it() -> None:
    lap = list(fast_laps("none", 144)[1])
    restart = lap[:3000] + [
        replace(f, current_race_time=f.current_race_time - 100.0) for f in lap[3000:6000]
    ]
    ss = samples(restart)
    assert sum(1 for s in ss if s.cut) == 1
    k = next(i for i, s in enumerate(ss) if s.cut)
    # the cut sample is smoothed only with samples after it
    raw_g = restart[k].accel_x / 9.80665
    assert abs(ss[k].lat_g - raw_g) < 0.5


# --- Engine power and gearing ----------------------------------------------------------------
def _with_power_peak(frames, peak: float) -> list[Frame]:  # type: ignore[no-untyped-def]
    out = []
    for f in frames:
        p = f.current_engine_rpm / f.engine_max_rpm
        shape = max(0.1, 1.0 - ((p - peak) / 0.6) ** 2)
        out.append(replace(f, power=f.throttle / 255 * 300_000.0 * shape))
    return out


def test_gearing_is_judged_against_the_learned_power_peak() -> None:
    lap = laps("gearing-long")[1]  # ends the longest straight at ~70 % of max rpm
    assert "gearing-long" in found(analyse(lap))  # linear power: peak unknown, old band

    late = analyse(_with_power_peak(lap, 0.85))
    assert late.metrics.peak_power_rpm_pct == pytest.approx(0.85, abs=0.03)
    assert "gearing-long" in found(late)  # 70 % is well short of the 85 % peak

    early = analyse(_with_power_peak(lap, 0.65))
    assert early.metrics.peak_power_rpm_pct == pytest.approx(0.65, abs=0.03)
    assert "gearing-long" not in found(early)  # already past peak power: not too long


def test_power_peak_needs_the_falling_side() -> None:
    assert analyse(laps("none")[1]).metrics.peak_power_rpm_pct is None  # power still rising


# --- Gamepad steering ------------------------------------------------------------------------
def _gamepad(frames) -> list[Frame]:  # type: ignore[no-untyped-def]
    """Stick amplitude that doesn't follow the wheel angle (the game sets that) and
    sits at full lock through most corners, like the recorded gamepad laps."""
    out = []
    for f in frames:
        gain = 2.0 + 10.0 * (0.5 + 0.5 * math.sin(2 * math.pi * f.current_race_time / 3.0))
        out.append(replace(f, steer=max(-127, min(127, round(f.steer * gain)))))
    return out


def test_yaw_model_is_dropped_when_steering_is_not_proportional() -> None:
    def fit(frames) -> YawFit:  # type: ignore[no-untyped-def]
        y = YawFit()
        for s in samples(frames):
            y.add(s)
        return y

    lap = laps("understeer")[1]
    assert fit(lap).model() is not None
    pad = fit(_gamepad(lap))
    assert not pad.linear() and pad.model() is None


def test_gamepad_understeer_is_still_found_from_slip_angles_with_a_caveat() -> None:
    la = analyse(_gamepad(laps("understeer")[1]))
    f = next(f for f in la.findings if f.id == "mid-understeer")
    assert "full lock" in f.evidence
    ref = next(f for f in analyse(laps("understeer")[1]).findings if f.id == "mid-understeer")
    assert f.confidence < ref.confidence
