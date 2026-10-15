"""Per-event records: corners (with entry/mid/exit phases), braking zones,
straights and bottoming hits.

The streaming :mod:`segmenter <pitwall.analysis.segments>` cuts the sample
stream into windows; the functions here turn one window into one record. Both
the per-lap analyzer and the live board use them, so a corner is judged the
same way in both places.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .samples import Sample
from .thresholds import (
    BALANCE_FLAG,
    BALANCE_SLIP_WEIGHT,
    BALANCE_YAW_WEIGHT,
    BRAKE_ON,
    CORNER_ENTER_G,
    CORNER_EXIT_G,
    CORNER_MIN_SPEED,
    COUNTERSTEER_MIN,
    HEAVY_BRAKE,
    HIGH_SPEED_CORNER,
    LOCK_DEEP_SLIP_RATIO,
    LOCK_GAP_S,
    LOCK_MAX_REAR_SLIP_ANGLE,
    LOCK_MIN_SPEED,
    LOCK_WHEEL_SPEED_RATIO,
    LOCKUP_MIN_S,
    MID_MIN_HALF_S,
    MID_SPEED_BAND,
    PHASE_LOADED_FRACTION,
    SLIP_LIMIT,
    STEER_PINNED,
    THROTTLE_ON,
    UNSTABLE_MIN_S,
    UNSTABLE_REAR_MARGIN,
    UNSTABLE_REAR_SLIP,
    WHEELSPIN_MIN_S,
    WHEELSPIN_SLIP_RATIO,
    YAW_FIT_MIN_STEER,
)
from .yaw import YawModel

PHASES = ("entry", "mid", "exit")

DRIVEN_AXLES: dict[str, tuple[str, ...]] = {
    "FWD": ("front",),
    "RWD": ("rear",),
    "AWD": ("front", "rear"),
}


# --- Windows (raw sample spans produced by the segmenter) ----------------------
@dataclass(slots=True)
class CornerWindow:
    """Samples from the start of the braking zone to the end of the exit window."""

    samples: list[Sample]
    seg_start: int  # first sample with lateral load (index into ``samples``)
    seg_end: int  # last sample with lateral load
    sign: int  # sign of lateral g in this corner
    partial: bool  # the corner was cut by the start or end of the data


@dataclass(slots=True)
class BrakeWindow:
    samples: list[Sample]
    partial: bool


# --- Records ---------------------------------------------------------------------
@dataclass(slots=True)
class PhaseStats:
    samples: int = 0  # loaded samples behind the averages
    balance: float | None = None  # combined, + understeer / - oversteer
    slip: float | None = None  # front minus rear normalised slip angle
    yaw: float | None = None  # yaw deficit vs expected (+ under-rotating)
    understeer_s: float = 0.0  # time with the front past the limit and balance > flag
    oversteer_s: float = 0.0
    countersteer_s: float = 0.0
    peak_front: float = 0.0
    peak_rear: float = 0.0
    seconds: float = 0.0  # loaded time behind the averages
    pinned_s: float = 0.0  # ... of which with the steering at full lock


@dataclass(slots=True)
class CornerRecord:
    sign: int
    t_start: float
    t_end: float
    start_dist: float
    apex_dist: float
    end_dist: float
    entry_speed: float
    min_speed: float
    exit_speed: float
    peak_lat_g: float
    heading_deg: float
    band: str  # "low" | "high"
    entry: PhaseStats
    mid: PhaseStats
    exit: PhaseStats
    spin_axle: str | None = None
    spin_s: float = 0.0
    spin_peak: float = 0.0
    spin_dist: float | None = None
    lap: int = 0
    partial: bool = False
    number: int = 0  # assigned by the consumer (1-based within a lap)

    def phase(self, name: str) -> PhaseStats:
        return getattr(self, name)


@dataclass(slots=True)
class BrakeRecord:
    t_start: float
    start_dist: float
    end_dist: float
    entry_speed: float
    exit_speed: float
    duration: float
    peak_decel_g: float
    lock_front_s: float = 0.0
    lock_rear_s: float = 0.0
    lock_front_dist: float | None = None
    lock_rear_dist: float | None = None
    unstable_s: float = 0.0
    unstable_dist: float | None = None
    partial: bool = False

    @property
    def locked_front(self) -> bool:
        return self.lock_front_s >= LOCKUP_MIN_S

    @property
    def locked_rear(self) -> bool:
        return self.lock_rear_s >= LOCKUP_MIN_S

    @property
    def unstable(self) -> bool:
        return self.unstable_s >= UNSTABLE_MIN_S


@dataclass(slots=True)
class StraightRecord:
    t_end: float
    start_dist: float
    end_dist: float
    duration: float
    end_speed: float
    end_gear: int
    end_rpm_pct: float  # max rpm fraction over the last END_OF_STRAIGHT_S
    gear_time_s: float  # time spent in end_gear before the straight ended
    limiter_s: float  # time on the limiter in end_gear
    max_gear: int
    cut_start: bool = False
    cut_end: bool = False

    @property
    def length(self) -> float:
        return self.end_dist - self.start_dist


@dataclass(slots=True)
class BottomingEvent:
    axle: str  # "front" | "rear"
    t: float
    dist: float
    speed: float
    duration: float


# --- Corner analysis ---------------------------------------------------------------
@dataclass(slots=True)
class _PhaseAcc:
    """Time-weighted sums for one phase (packet rate doesn't bias the means)."""

    n: int = 0
    w: float = 0.0
    bal: float = 0.0
    slip: float = 0.0
    yaw: float = 0.0
    w_yaw: float = 0.0
    pinned: float = 0.0
    stats: PhaseStats = field(default_factory=PhaseStats)

    def finish(self) -> PhaseStats:
        st = self.stats
        st.samples = self.n
        st.seconds = self.w
        st.pinned_s = self.pinned
        if self.w > 0:
            st.balance = self.bal / self.w
            st.slip = self.slip / self.w
        if self.w_yaw > 0:
            st.yaw = self.yaw / self.w_yaw
        return st


def _yaw_balance(
    s: Sample, turn: int, model: YawModel | None, steer_sign: int, yaw_sign: int
) -> float | None:
    """Yaw deficit vs the in-grip model: + yaws less than asked (understeer)."""
    steer_in = s.steer * steer_sign * turn
    if steer_in <= -COUNTERSTEER_MIN and s.lat_g * turn >= CORNER_EXIT_G:
        return -1.0  # counter-steering while still cornering: the rear is out
    if model is None or steer_in < YAW_FIT_MIN_STEER or s.v < CORNER_MIN_SPEED:
        return None
    expected = model.expected_curvature(steer_in, s.v)
    if not expected:
        return None
    actual = s.yaw * yaw_sign * turn / s.v
    yb = 1.0 - actual / expected
    return -1.0 if yb < -1.0 else (1.0 if yb > 1.0 else yb)


def analyze_corner(
    w: CornerWindow,
    model: YawModel | None,
    drivetrain: str,
    steer_sign: int = 1,
    yaw_sign: int = 1,
) -> CornerRecord:
    ss = w.samples
    a, b = w.seg_start, w.seg_end
    if model is not None:
        steer_sign, yaw_sign = model.steer_sign, model.yaw_sign

    apex = a
    for k in range(a + 1, b + 1):
        if ss[k].v < ss[apex].v:
            apex = k
    vmin = ss[apex].v
    vth = vmin * (1.0 + MID_SPEED_BAND)
    t_apex = ss[apex].t
    ms = apex
    while ms > a and (ss[ms - 1].v <= vth or t_apex - ss[ms - 1].t <= MID_MIN_HALF_S):
        ms -= 1
    me = apex
    while me < b and (ss[me + 1].v <= vth or ss[me + 1].t - t_apex <= MID_MIN_HALF_S):
        me += 1

    peak_lat = 0.0
    for k in range(a, b + 1):
        x = abs(ss[k].lat_g)
        if x > peak_lat:
            peak_lat = x
    loaded = PHASE_LOADED_FRACTION * peak_lat
    turn = w.sign

    accs = (_PhaseAcc(), _PhaseAcc(), _PhaseAcc())
    heading = 0.0
    for k in range(a, b + 1):
        s = ss[k]
        acc = accs[0] if k < ms else (accs[1] if k <= me else accs[2])
        st = acc.stats
        heading += abs(s.yaw) * s.dt
        slip = s.sa_f - s.sa_r
        yb = _yaw_balance(s, turn, model, steer_sign, yaw_sign)
        bal = slip if yb is None else BALANCE_SLIP_WEIGHT * slip + BALANCE_YAW_WEIGHT * yb
        if abs(s.lat_g) >= loaded:
            dt = s.dt
            acc.n += 1
            acc.w += dt
            acc.bal += bal * dt
            acc.slip += slip * dt
            if s.steer >= STEER_PINNED or s.steer <= -STEER_PINNED:
                acc.pinned += dt
            if yb is not None:
                acc.yaw += yb * dt
                acc.w_yaw += dt
        if s.sa_f > st.peak_front:
            st.peak_front = s.sa_f
        if s.sa_r > st.peak_rear:
            st.peak_rear = s.sa_r
        if s.sa_f >= SLIP_LIMIT and bal >= BALANCE_FLAG:
            st.understeer_s += s.dt
        if yb == -1.0:
            st.countersteer_s += s.dt
        if (s.sa_r >= SLIP_LIMIT and bal <= -BALANCE_FLAG) or (
            yb == -1.0 and s.sa_r >= 0.9 * SLIP_LIMIT
        ):
            st.oversteer_s += s.dt

    # wheelspin from the end of mid-corner to the end of the exit window
    driven = DRIVEN_AXLES.get(drivetrain, ("front", "rear"))
    spin = {"front": 0.0, "rear": 0.0}
    peak = {"front": 0.0, "rear": 0.0}
    first: dict[str, float] = {}
    for k in range(me + 1, len(ss)):
        s = ss[k]
        if s.thr < THROTTLE_ON:
            continue
        for axle in driven:
            sr = s.sr_f_max if axle == "front" else s.sr_r_max
            if sr >= WHEELSPIN_SLIP_RATIO:
                spin[axle] += s.dt
                if sr > peak[axle]:
                    peak[axle] = sr
                first.setdefault(axle, s.dist)
    spin_axle = max(driven, key=lambda ax: spin[ax])
    has_spin = spin[spin_axle] >= WHEELSPIN_MIN_S

    return CornerRecord(
        sign=turn,
        t_start=ss[a].t,
        t_end=ss[b].t,
        start_dist=ss[a].dist,
        apex_dist=ss[apex].dist,
        end_dist=ss[b].dist,
        entry_speed=ss[0].v,
        min_speed=vmin,
        exit_speed=ss[-1].v,
        peak_lat_g=peak_lat,
        heading_deg=heading * 57.29577951308232,
        band="high" if vmin >= HIGH_SPEED_CORNER else "low",
        entry=accs[0].finish(),
        mid=accs[1].finish(),
        exit=accs[2].finish(),
        spin_axle=spin_axle if has_spin else None,
        spin_s=spin[spin_axle] if has_spin else 0.0,
        spin_peak=peak[spin_axle] if has_spin else 0.0,
        spin_dist=first.get(spin_axle) if has_spin else None,
        lap=ss[apex].lap,
        partial=w.partial,
    )


def _is_locked(ws: float | None, sr: float) -> bool:
    return (ws is not None and ws <= LOCK_WHEEL_SPEED_RATIO) or sr <= LOCK_DEEP_SLIP_RATIO


def _lock_time(ss: list[Sample], front: bool) -> tuple[float, float | None]:
    """Total time of lock runs on one axle, and where the first one started.

    A run is a stretch of braking at speed with a loaded wheel (nearly) stopped,
    allowing ``LOCK_GAP_S`` gaps. It counts if it lasts ``LOCKUP_MIN_S`` and
    began before the car was already sideways (a spin stops wheels too).
    """
    total, where = 0.0, None
    start = last = end = 0.0
    start_dist = 0.0
    valid = active = False
    for s in ss:
        locked = (
            s.brk >= BRAKE_ON
            and s.v >= LOCK_MIN_SPEED
            and _is_locked(s.ws_f if front else s.ws_r, s.sr_f_min if front else s.sr_r_min)
        )
        if locked:
            if not active or s.t - last > LOCK_GAP_S:
                if active and valid and end - start >= LOCKUP_MIN_S:
                    total += end - start
                    where = start_dist if where is None else where
                active = True
                start, start_dist = s.t, s.dist
                valid = s.sa_r < LOCK_MAX_REAR_SLIP_ANGLE
            last, end = s.t, s.t + s.dt
    if active and valid and end - start >= LOCKUP_MIN_S:
        total += end - start
        where = start_dist if where is None else where
    return total, where


def analyze_brake(w: BrakeWindow) -> BrakeRecord:
    ss = w.samples
    rec = BrakeRecord(
        t_start=ss[0].t,
        start_dist=ss[0].dist,
        end_dist=ss[-1].dist,
        entry_speed=ss[0].v,
        exit_speed=ss[-1].v,
        duration=ss[-1].t - ss[0].t + ss[-1].dt,
        peak_decel_g=max(0.0, -min(s.lon_g for s in ss)),
        partial=w.partial,
    )
    rec.lock_front_s, rec.lock_front_dist = _lock_time(ss, front=True)
    rec.lock_rear_s, rec.lock_rear_dist = _lock_time(ss, front=False)
    for s in ss:
        if (
            s.brk >= HEAVY_BRAKE
            and abs(s.lat_g) < CORNER_ENTER_G
            and s.sa_r >= UNSTABLE_REAR_SLIP
            and s.sa_r - s.sa_f >= UNSTABLE_REAR_MARGIN
        ):
            rec.unstable_s += s.dt
            if rec.unstable_dist is None:
                rec.unstable_dist = s.dist
    return rec
