"""Per-lap analysis: metrics, corners, findings and lap-level recommendations."""

from __future__ import annotations

from collections.abc import Sequence
from statistics import median

from pitwall.telemetry.model import Frame

from .assess import Evidence, assess_all, build_board, finding_from, recommend
from .power import PowerCurve
from .records import (
    BottomingEvent,
    BrakeRecord,
    BrakeWindow,
    CornerRecord,
    CornerWindow,
    StraightRecord,
    analyze_brake,
    analyze_corner,
)
from .results import (
    CornerSummary,
    LapAnalysis,
    LapContext,
    LapMetrics,
    Recommendation,
    drivetrain_name,
)
from .samples import Sample, SampleBuilder, f_to_c
from .segments import Segmenter
from .text import lap_limits
from .thresholds import (
    BRAKE_ON,
    FULL_THROTTLE,
    LIMITER_MIN_RUN_S,
    LIMITER_RPM_PCT,
    LONG_STRAIGHT_MIN_M,
    MIN_FINDING_SEVERITY,
)
from .yaw import YawFit

_WHEELS = ("fl", "fr", "rl", "rr")
_MAX_FORWARD_GEAR = 10


class _Collected:
    """Everything one pass over a lap produces."""

    def __init__(self) -> None:
        self.samples: list[Sample] = []
        self.corner_windows: list[CornerWindow] = []
        self.brake_windows: list[BrakeWindow] = []
        self.straights: list[StraightRecord] = []
        self.bottoming: list[BottomingEvent] = []

    def take(self, segs: Sequence[object] | None) -> None:
        if not segs:
            return
        for seg in segs:
            if isinstance(seg, CornerWindow):
                self.corner_windows.append(seg)
            elif isinstance(seg, BrakeWindow):
                self.brake_windows.append(seg)
            elif isinstance(seg, StraightRecord):
                self.straights.append(seg)
            elif isinstance(seg, BottomingEvent):
                self.bottoming.append(seg)


def _corner_lookup(corners: Sequence[CornerRecord]):
    def corner_at(dist: float) -> int | None:
        """Corner a position belongs to: inside it, or the one it leads into."""
        for c in corners:
            if dist <= c.end_dist + 30.0:
                return c.number if dist >= c.start_dist - 250.0 else None
        return None

    return corner_at


def _tire_avg(samples: Sequence[Sample]) -> tuple[float, float, float, float] | None:
    if not samples:
        return None
    sums = [0.0, 0.0, 0.0, 0.0]
    total = 0.0
    for s in samples:
        t, dt = s.temps, s.dt
        sums[0] += t[0] * dt
        sums[1] += t[1] * dt
        sums[2] += t[2] * dt
        sums[3] += t[3] * dt
        total += dt
    return tuple(f_to_c(x / total) for x in sums)  # type: ignore[return-value]


def _phase_median(corners: Sequence[CornerRecord], phase: str) -> float | None:
    vals = [c.phase(phase).balance for c in corners if c.phase(phase).balance is not None]
    return median(vals) if vals else None


def _metrics(
    frames: Sequence[Frame],
    col: _Collected,
    corners: Sequence[CornerRecord],
    brakes: Sequence[BrakeRecord],
    lap_time: float | None,
) -> LapMetrics:
    ss = col.samples
    m = LapMetrics(lap_time=lap_time, frames=len(ss))
    if not ss:
        return m
    total_t = sum(s.dt for s in ss)
    m.distance = ss[-1].dist
    m.max_speed = max(s.v for s in ss)
    m.avg_speed = m.distance / total_t if total_t > 0 else 0.0
    m.sample_rate_hz = len(ss) / total_t if total_t > 0 else 0.0
    full = brake = limiter = run = 0.0
    top = 0
    for s in ss:
        if s.thr >= FULL_THROTTLE:
            full += s.dt
        if s.brk >= BRAKE_ON:
            brake += s.dt
        if s.thr >= FULL_THROTTLE and s.rpm_pct >= LIMITER_RPM_PCT:
            run += s.dt
        else:
            if run >= LIMITER_MIN_RUN_S:
                limiter += run
            run = 0.0
        if top < s.gear <= _MAX_FORWARD_GEAR:
            top = s.gear
    if run >= LIMITER_MIN_RUN_S:
        limiter += run
    m.full_throttle_pct = full / total_t if total_t else 0.0
    m.braking_pct = brake / total_t if total_t else 0.0
    m.limiter_time_s = limiter
    m.top_gear_used = top
    m.top_gear_max_rpm_pct = max((s.rpm_pct for s in ss if s.gear == top), default=0.0)

    whole = [c for c in corners if not c.partial]
    m.corners = len(whole)
    m.corners_slow = sum(1 for c in whole if c.band == "low")
    m.corners_fast = m.corners - m.corners_slow
    m.balance = {p: _phase_median(whole, p) for p in ("entry", "mid", "exit")}
    m.balance_by_speed = {
        band: {
            p: _phase_median([c for c in whole if c.band == band], p)
            for p in ("entry", "mid", "exit")
        }
        for band in ("low", "high")
    }
    m.wheelspin_events = sum(1 for c in whole if c.spin_axle)
    full_brakes = [b for b in brakes if not b.partial]
    m.braking_zones = len(full_brakes)
    m.lockups = {
        "front": sum(1 for b in full_brakes if b.locked_front),
        "rear": sum(1 for b in full_brakes if b.locked_rear),
    }
    m.braking_instability_events = sum(1 for b in full_brakes if b.unstable)
    m.bottoming = {
        "front": sum(1 for e in col.bottoming if e.axle == "front"),
        "rear": sum(1 for e in col.bottoming if e.axle == "rear"),
    }
    m.bottoming_events = m.bottoming["front"] + m.bottoming["rear"]
    long_ones = [s for s in col.straights if not s.cut_end]
    if col.straights:
        m.longest_straight_m = max(s.length for s in col.straights)
    if long_ones:
        st = max(long_ones, key=lambda s: s.length)
        if st.length >= LONG_STRAIGHT_MIN_M:
            m.end_of_straight_rpm_pct = st.end_rpm_pct
            m.end_of_straight_gear = st.end_gear

    avg = _tire_avg(ss) or (0.0, 0.0, 0.0, 0.0)
    for k, w in enumerate(_WHEELS):
        m.tire_temp_avg[w] = avg[k]
        m.tire_temp_max[w] = f_to_c(max(s.temps[k] for s in ss))
    first, last = frames[0].tire_wear, frames[-1].tire_wear
    m.tire_wear_delta = {w: abs(last[k] - first[k]) for k, w in enumerate(_WHEELS)}
    return m


def _lap_time(frames: Sequence[Frame], ctx: LapContext, col: _Collected) -> float | None:
    if ctx.lap_time is not None:
        return ctx.lap_time
    if not frames:
        return None
    last = frames[-1].current_lap
    if last > 0:
        return last
    return sum(s.dt for s in col.samples) or None


def analyze_lap(frames: Sequence[Frame], ctx: LapContext) -> LapAnalysis:
    """Analyse one lap of frames (raw game units) into metrics and findings."""
    frames = [f for f in frames if f.is_race_on]
    drivetrain = drivetrain_name(
        ctx.drivetrain if ctx.drivetrain is not None else (frames[0].drivetrain if frames else None)
    )
    tune_values = dict(ctx.tune_values or {})

    builder, seg, fit, col = SampleBuilder(), Segmenter(), YawFit(), _Collected()
    power = PowerCurve()

    def take(s: Sample) -> None:
        if s.cut:  # rewind or restart: nothing open may span it
            col.take(seg.flush())
            seg.reset()
        col.samples.append(s)
        fit.add(s)
        power.add(s)
        col.take(seg.push(s))

    for f in frames:
        for s in builder.push(f):
            take(s)
    for s in builder.flush():
        take(s)
    col.take(seg.flush())

    model = fit.model()
    corners: list[CornerRecord] = []
    for w in col.corner_windows:
        rec = analyze_corner(w, model, drivetrain, fit.steer_sign, fit.yaw_sign)
        corners.append(rec)
    for n, c in enumerate((c for c in corners if not c.partial), start=1):
        c.number = n
    brakes = [analyze_brake(w) for w in col.brake_windows]

    lap_time = _lap_time(frames, ctx, col)
    metrics = _metrics(frames, col, corners, brakes, lap_time)
    metrics.peak_power_rpm_pct = power.peak_rpm_pct()
    ev = Evidence(
        corners=corners,
        brakes=brakes,
        straights=col.straights,
        bottoming=col.bottoming,
        tire_avg_c=_tire_avg(col.samples),
        tire_seconds=sum(s.dt for s in col.samples),
        top_gear=metrics.top_gear_used,
        drivetrain=drivetrain,
        peak_power_rpm=metrics.peak_power_rpm_pct,
        corner_at=_corner_lookup([c for c in corners if not c.partial]),
    )
    assessments = assess_all(ev)
    items, _focus = build_board(
        assessments, drivetrain=drivetrain, unit_system=ctx.unit_system, tune_values=tune_values
    )

    found = [
        a
        for a in assessments
        if a.finding_id and not a.collecting and a.severity >= MIN_FINDING_SEVERITY
    ]
    found.sort(key=lambda a: -(a.severity * a.confidence))
    findings = tuple(finding_from(a) for a in found)
    recs: list[Recommendation] = []
    for a in found:
        rec = recommend(
            a.finding_id or "",
            a.axle,
            a.evidence,
            a.confidence,
            drivetrain=drivetrain,
            unit_system=ctx.unit_system,
            tune_values=tune_values,
            priority=len(recs) + 1,
            detail=a.detail,
        )
        if rec is not None and all(r.setting != rec.setting for r in recs):
            recs.append(rec)

    summaries = tuple(
        CornerSummary(
            number=c.number,
            start_distance=c.start_dist,
            apex_distance=c.apex_dist,
            end_distance=c.end_dist,
            min_speed=c.min_speed,
            peak_lat_g=c.peak_lat_g,
            speed_band=c.band,
            balance={p: c.phase(p).balance for p in ("entry", "mid", "exit")},
            wheelspin=c.spin_axle is not None,
        )
        for c in corners
        if not c.partial
    )
    return LapAnalysis(
        lap_number=frames[0].lap_number + 1 if frames else None,  # 1-based, like stored laps
        lap_kind=ctx.lap_kind,
        valid=ctx.lap_valid,
        drivetrain=drivetrain,
        lap_time=lap_time,
        metrics=metrics,
        corners=summaries,
        findings=findings,
        recommendations=tuple(recs),
        items=tuple(items),
        limits=tuple(lap_limits(tune_values, findings, recs, len(frames))),
    )
