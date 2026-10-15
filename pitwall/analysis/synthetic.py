"""Deterministic synthetic laps with injectable handling issues.

A small lap simulator drives a fixed closed track (about 4.6 km, eight corners:
five slow, three fast) with a point-mass car: grip limited by a friction circle
with aero, power and drag limits, a six-speed gearbox. On top of that ideal lap
it synthesises what Data Out would report (slip angles and ratios, suspension
travel, tire temperatures, inputs, rpm, ...) and can inject issues:

``none``, ``understeer``, ``high-speed-understeer``, ``oversteer-entry``,
``oversteer-exit``, ``unstable-braking``, ``wheelspin``, ``lockup-front``,
``lockup-rear``, ``bottoming``, ``bottoming-rear``, ``gearing-short``,
``gearing-long``.

Use :func:`generate_lap` / :func:`generate_laps` for tests and
:class:`SyntheticDriver` (``.lap()``, ``.frames()``) to stream an endless,
continuous session, e.g. from a UDP simulator. Output is fully determined by
the arguments (seeded ``random.Random``, no global state).

Sign conventions used here: right turn = positive lateral acceleration
(``accel_x``), positive yaw rate and positive steering.
"""

from __future__ import annotations

import math
import random
from bisect import bisect_right
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from functools import lru_cache

from pitwall.telemetry.model import Corners, Frame

G = 9.80665

ISSUES = (
    "none",
    "understeer",
    "high-speed-understeer",
    "oversteer-entry",
    "oversteer-exit",
    "unstable-braking",
    "wheelspin",
    "lockup-front",
    "lockup-rear",
    "bottoming",
    "bottoming-rear",
    "gearing-short",
    "gearing-long",
)
DRIVETRAINS = ("FWD", "RWD", "AWD")

_DS = 1.0  # track grid, metres
_SMOOTH_M = 31  # curvature smoothing window (clothoid-like transitions)
_START_OFFSET_M = 300.0  # start/finish line position on the main straight
_TS_MOD = 1 << 32
_SLIP_PER_UNIT = 0.13  # real slip per unit of normalised slip ratio (as seen in the game)
_LOCKED_SLIP_RATIO = -7.2  # normalised slip ratio of a stopped wheel
_ABS_HZ = 3.0  # ABS modulation cycles per second

# (length for straights / radius for arcs, turn in degrees: 0 = straight, + = right)
_SEGMENTS: tuple[tuple[float, float], ...] = (
    (900.0, 0.0),  # main straight
    (25.0, 110.0),  # T1 hairpin
    (220.0, 0.0),
    (120.0, -45.0),  # T2 fast left
    (250.0, 0.0),
    (200.0, 80.0),  # T3 fast right
    (350.0, 0.0),  # length adjusted to close the loop
    (40.0, 90.0),  # T4
    (150.0, 0.0),
    (35.0, -60.0),  # T5 left
    (40.0, 0.0),
    (60.0, 75.0),  # T6 right
    (450.0, 0.0),  # length adjusted to close the loop
    (230.0, 70.0),  # T7 fast sweeper
    (200.0, 0.0),
    (30.0, 40.0),  # T8
)
_ADJUSTABLE = (6, 12)


# --- Track ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Track:
    kappa: tuple[float, ...]  # curvature per metre, + = right
    heading: tuple[float, ...]  # n + 1 values
    x: tuple[float, ...]
    z: tuple[float, ...]

    @property
    def length(self) -> float:
        return len(self.kappa) * _DS


def _raw_kappa(lengths: list[float]) -> tuple[list[float], list[int]]:
    k: list[float] = []
    starts: list[int] = []
    for (_, turn), length in zip(_SEGMENTS, lengths, strict=True):
        starts.append(len(k))
        m = max(1, round(length / _DS))
        k += [0.0] * m if turn == 0 else [math.radians(turn) / (m * _DS)] * m
    return k, starts


def _smooth(k: list[float], w: int) -> list[float]:
    n, h = len(k), w // 2
    acc = sum(k[j % n] for j in range(-h, h + 1))
    out = []
    for i in range(n):
        out.append(acc / w)
        acc += k[(i + h + 1) % n] - k[(i - h) % n]
    return out


def _integrate(k: list[float]) -> tuple[list[float], list[float], list[float]]:
    h, x, z = [0.0], [0.0], [0.0]
    for ki in k:
        mid = h[-1] + ki * _DS / 2
        x.append(x[-1] + math.sin(mid) * _DS)
        z.append(z[-1] + math.cos(mid) * _DS)
        h.append(h[-1] + ki * _DS)
    return h, x, z


@lru_cache(maxsize=1)
def track() -> Track:
    """The synthetic circuit (closed loop, start/finish on the main straight)."""
    lengths = [s if t == 0 else s * math.radians(abs(t)) for s, t in _SEGMENTS]
    for _ in range(2):  # close the loop by stretching two non-parallel straights
        raw, starts = _raw_kappa(lengths)
        k = _smooth(raw, _SMOOTH_M)
        h, x, z = _integrate(k)
        ex, ez = x[-1] - x[0], z[-1] - z[0]
        a, b = _ADJUSTABLE
        ha = h[starts[a] + round(lengths[a] / 2)]
        hb = h[starts[b] + round(lengths[b] / 2)]
        det = math.sin(ha) * math.cos(hb) - math.sin(hb) * math.cos(ha)
        lengths[a] += (-ex * math.cos(hb) + ez * math.sin(hb)) / det
        lengths[b] += (-math.sin(ha) * ez + math.cos(ha) * ex) / det
    raw, _ = _raw_kappa(lengths)
    k = _smooth(raw, _SMOOTH_M)
    h, x, z = _integrate(k)
    n = len(k)
    ex, ez = x[-1] - x[0], z[-1] - z[0]
    x = [xi - ex * i / n for i, xi in enumerate(x)]
    z = [zi - ez * i / n for i, zi in enumerate(z)]
    shift = round(_START_OFFSET_M / _DS)
    k = k[shift:] + k[:shift]
    h = h[shift:n] + [hi + 2 * math.pi for hi in h[: shift + 1]]
    x = x[shift:n] + x[: shift + 1]
    z = z[shift:n] + z[: shift + 1]
    return Track(tuple(k), tuple(h), tuple(x), tuple(z))


# --- Car and lap profile ------------------------------------------------------------------
@dataclass(frozen=True)
class Car:
    mu_lat: float = 1.30  # g
    aero_lat: float = 0.00012  # g per (m/s)^2
    mu_brake: float = 1.30
    aero_brake: float = 0.00010
    power: float = 255.0  # W/kg
    drag: float = 0.00040  # 1/m
    wheelbase: float = 2.6
    us_gradient: float = 0.0006  # s^2/m
    steer_lock: float = 0.25  # rad of road-wheel angle at full steer
    wheel_radius: float = 0.34  # driven wheels, for rpm
    wheel_radii: tuple[float, ...] = (0.323, 0.323, 0.356, 0.356)  # rolling radius per wheel
    gears: tuple[float, ...] = (3.30, 2.40, 1.86, 1.50, 1.25, 1.06)
    max_rpm: float = 8000.0
    idle_rpm: float = 900.0
    shift_pct: float = 0.95
    margin: float = 0.95  # share of the grip the driver uses

    def traction(self, drivetrain: str) -> float:
        return {"FWD": 0.75, "RWD": 0.85, "AWD": 1.05}[drivetrain] * G

    def rpm_factor(self, final_drive: float) -> float:
        """rpm per (m/s) per unit gear ratio."""
        return final_drive * 60.0 / (2 * math.pi * self.wheel_radius)


CAR = Car()


@dataclass
class _Profile:
    v: list[float]
    a_lon: list[float]
    t: list[float]  # n + 1, lap time = t[-1]
    throttle: list[float]
    brake: list[float]
    limiter: list[bool]


def _profile(
    trk: Track, car: Car, drivetrain: str, pace: float, grip: list[float], v_cap: float
) -> _Profile:
    kap = trk.kappa
    n = len(kap)
    a0 = G * car.mu_lat * car.margin * pace
    b0 = G * car.aero_lat * car.margin * pace
    vlim = []
    for i in range(n):
        k = abs(kap[i])
        a, b = a0 * grip[i], b0 * grip[i]
        vlim.append(min(v_cap, math.sqrt(a / (k - b)) if k > b else v_cap))
    start = min(range(n), key=vlim.__getitem__)
    trac = car.traction(drivetrain)

    def friction(i: int, vv: float) -> float:
        alat = (a0 + b0 * vv * vv) * grip[i]
        u = min(1.0, vv * vv * abs(kap[i]) / alat)
        return math.sqrt(max(0.04, 1.0 - u * u))

    v = [0.0] * n
    v[start] = vlim[start]
    for step in range(1, n):
        i, p = (start + step) % n, (start + step - 1) % n
        vp = v[p]
        acc = min(trac, car.power / max(vp, 1.0)) - car.drag * vp * vp
        vn = math.sqrt(max(1.0, vp * vp + 2 * acc * friction(p, vp) * _DS))
        v[i] = min(vlim[i], vn)
    for step in range(1, n):
        i, nx = (start - step) % n, (start - step + 1) % n
        vn = v[nx]
        dec = G * (car.mu_brake + car.aero_brake * vn * vn) * car.margin * pace
        dec += car.drag * vn * vn
        v[i] = min(v[i], math.sqrt(vn * vn + 2 * dec * friction(nx, vn) * _DS))

    a_lon, t, thr, brk, lim = [], [0.0], [], [], []
    for i in range(n):
        vi, vn = v[i], v[(i + 1) % n]
        a = (vn * vn - vi * vi) / (2 * _DS)
        a_lon.append(a)
        t.append(t[-1] + 2 * _DS / (vi + vn))
        a_full = min(trac, car.power / max(vi, 1.0)) - car.drag * vi * vi
        dec_full = G * (car.mu_brake + car.aero_brake * vi * vi) * car.margin * pace
        on_limiter = vi >= v_cap - 0.3
        if a < -0.8:
            thr.append(0.0)
            brk.append(min(1.0, max(0.15, -a / dec_full)))
        elif on_limiter or a >= 0.9 * a_full - 0.05:
            thr.append(1.0)
            brk.append(0.0)
        elif a > 0.2:
            thr.append(min(1.0, max(0.3, a / max(a_full, 0.3))))
            brk.append(0.0)
        else:
            thr.append(0.3)
            brk.append(0.0)
        lim.append(on_limiter)
    return _Profile(v, a_lon, t, thr, brk, lim)


@lru_cache(maxsize=8)
def _clean_peak_speed(drivetrain: str) -> float:
    trk = track()
    prof = _profile(trk, CAR, drivetrain, 1.0, [1.0] * len(trk.kappa), 1e9)
    return max(prof.v)


def final_drive_for(drivetrain: str, rpm_pct_at_peak: float) -> float:
    """Final drive that puts top gear at ``rpm_pct_at_peak`` at the clean lap's top speed."""
    omega = CAR.max_rpm * rpm_pct_at_peak * 2 * math.pi / 60
    return omega * CAR.wheel_radius / (_clean_peak_speed(drivetrain) * CAR.gears[-1])


# --- Issue injection ----------------------------------------------------------------------
@dataclass
class _GridCorner:
    a: int  # first index with lateral load
    b: int  # last index with lateral load
    e: int  # end of braking (entry -> mid)
    x: int  # start of acceleration (mid -> exit)
    apex: int
    v_apex: float
    sign: int


@dataclass
class _Plan:
    d_sa_f: list[float]
    d_sa_r: list[float]
    d_sr_f: list[float]
    d_sr_r: list[float]
    steer_mul: list[float]
    d_yaw: list[float]
    d_susp_f: list[float]
    d_susp_r: list[float]
    grip: list[float]
    lock_f: list[float]  # 1.0 where the front wheels are locked
    lock_r: list[float]
    susp_offset_f: float = 0.0
    susp_offset_r: float = 0.0


def _grid_corners(trk: Track, prof: _Profile) -> list[_GridCorner]:
    kap, v, a_lon = trk.kappa, prof.v, prof.a_lon
    n = len(kap)
    lat = [v[i] * v[i] * kap[i] / G for i in range(n)]
    out = []
    i = 0
    while i < n:
        if abs(lat[i]) < 0.3:
            i += 1
            continue
        sign = 1 if lat[i] > 0 else -1
        a = i
        while i + 1 < n and lat[i + 1] * sign >= 0.3:
            i += 1
        b = i
        apex = min(range(a, b + 1), key=v.__getitem__)
        e = next((j for j in range(a, apex + 1) if a_lon[j] >= -0.8), apex)
        x = next((j for j in range(apex, b + 1) if a_lon[j] > 0.3), b)
        out.append(_GridCorner(a, b, e, x, apex, v[apex], sign))
        i += 1
    return out


def _brake_zones(prof: _Profile) -> list[tuple[int, int]]:
    zones, i, n = [], 0, len(prof.a_lon)
    while i < n:
        if prof.a_lon[i] < -3.0:
            a = i
            while i + 1 < n and prof.a_lon[i + 1] < -3.0:
                i += 1
            if i - a >= 20:
                zones.append((a, i))
        i += 1
    return zones


def _bump(m: int) -> list[float]:
    return [math.sin(math.pi * (j + 0.5) / m) for j in range(m)]


def _plateau(m: int) -> list[float]:
    return [min(1.0, 1.8 * s) for s in _bump(m)]


def _plan(
    issues: frozenset[str],
    trk: Track,
    base: _Profile,
    drivetrain: str,
    rng: random.Random,
    sev: float,
) -> _Plan:
    n = len(trk.kappa)
    p = _Plan(
        d_sa_f=[0.0] * n,
        d_sa_r=[0.0] * n,
        d_sr_f=[0.0] * n,
        d_sr_r=[0.0] * n,
        steer_mul=[1.0] * n,
        d_yaw=[0.0] * n,
        d_susp_f=[0.0] * n,
        d_susp_r=[0.0] * n,
        grip=[1.0] * n,
        lock_f=[0.0] * n,
        lock_r=[0.0] * n,
    )
    corners = _grid_corners(trk, base)
    zones = _brake_zones(base)

    def add(arr: list[float], lo: int, shape: list[float], amount: float) -> None:
        for j, sh in enumerate(shape):
            arr[(lo + j) % n] += amount * sh

    # compressions that exist on every lap; the "bottoming" issues make them hit
    fastest = max(corners, key=lambda c: c.v_apex)
    spots = (150, 380, fastest.apex)
    for spot in spots:
        add(p.d_susp_f, spot - 4, _bump(9), 0.10)
        add(p.d_susp_r, spot + 2, _bump(9), 0.10)

    if issues & {"understeer", "high-speed-understeer"}:
        for c in corners:
            if "understeer" not in issues and c.v_apex < 36.0:
                continue
            lo, hi = c.a + (c.e - c.a) // 2, c.x + (c.b - c.x) // 2
            shape = _plateau(hi - lo + 1)
            rf = rng.uniform(0.85, 1.15)
            add(p.d_sa_f, lo, shape, 0.55 * sev * rf)
            add(p.d_sa_r, lo, shape, -0.06)
            add(p.steer_mul, lo, shape, 0.5 * sev)
            for j, sh in enumerate(shape):
                p.grip[lo + j] = min(p.grip[lo + j], 1.0 - 0.05 * sev * sh)
    if "oversteer-exit" in issues:
        for c in corners:
            if c.v_apex >= 30.0:
                continue
            lo, hi = c.x, c.b + 10
            shape, rf = _bump(hi - lo + 1), rng.uniform(0.85, 1.15)
            add(p.d_sa_r, lo, shape, 0.7 * sev * rf)
            add(p.d_sa_f, lo, shape, -0.05)
            add(p.d_yaw, lo, shape, 0.15 * sev)
            add(p.steer_mul, lo, shape, -1.4 * sev)
            add(p.d_sr_r if drivetrain != "FWD" else p.d_sr_f, lo, shape, 0.3)
    if "oversteer-entry" in issues:
        for c in corners:
            if c.e - c.a < 8:
                continue
            lo, hi = c.a, c.e + (c.x - c.e) // 3
            shape, rf = _bump(hi - lo + 1), rng.uniform(0.85, 1.15)
            add(p.d_sa_r, lo, shape, 0.7 * sev * rf)
            add(p.d_yaw, lo, shape, 0.12 * sev)
            add(p.steer_mul, lo, shape, -1.4 * sev)
    if "unstable-braking" in issues:
        for z0, z1 in zones:
            straight = next((j for j in range(z0, z1 + 1) if abs(trk.kappa[j]) > 1 / 800), z1)
            m = int((straight - z0) * 0.7)
            if m < 10:
                continue
            shape, rf = _bump(m), rng.uniform(0.85, 1.15)
            add(p.d_sa_r, z0, shape, 1.0 * sev * rf)
            add(p.d_sa_f, z0, shape, 0.1)
    if "wheelspin" in issues:
        for c in corners:
            if c.v_apex >= 30.0:
                continue
            lo, hi = c.x + (c.b - c.x) // 4, c.b + 25
            shape, rf = _bump(hi - lo + 1), rng.uniform(0.85, 1.15)
            if drivetrain == "FWD":
                add(p.d_sr_f, lo, shape, 1.1 * sev * rf)
            else:
                add(p.d_sr_r, lo, shape, 1.1 * sev * rf)
                if drivetrain == "AWD":
                    add(p.d_sr_f, lo, shape, 0.4 * sev * rf)
    for axle in ("front", "rear"):
        if f"lockup-{axle}" not in issues:
            continue
        # a real lock (ABS off or overwhelmed): the wheels stop for a moment
        for z0, z1 in zones:
            if z1 - z0 < 30:
                continue
            length = max(10, int((z1 - z0) * 0.2 * sev * rng.uniform(0.85, 1.15)))
            lo = z0 + (z1 - z0) // 8
            lock = p.lock_f if axle == "front" else p.lock_r
            for k in range(lo, min(lo + length, z1)):
                lock[k] = 1.0
            if axle == "rear":
                add(p.d_sa_r, lo, _bump(length), 0.15)
    for issue, front in (("bottoming", True), ("bottoming-rear", False)):
        if issue not in issues:
            continue
        for spot in spots:
            add(
                p.d_susp_f if front else p.d_susp_r,
                spot - 4 if front else spot + 2,
                _bump(9),
                0.30 * sev,
            )
        if front:
            p.susp_offset_f = 0.12 * sev
        else:
            p.susp_offset_r = 0.12 * sev
    return p


# --- Frames --------------------------------------------------------------------------------
class SyntheticDriver:
    """Drives consecutive synthetic laps as one continuous Data Out stream."""

    def __init__(
        self,
        issue: str | Iterable[str] = "none",
        *,
        drivetrain: str = "RWD",
        seed: int = 0,
        severity: float = 1.0,
        hz: float = 60.0,
        start_time: float = 1000.0,
        car_ordinal: int = 9001,
        track_ordinal: int = 9001,
    ) -> None:
        issues = frozenset([issue] if isinstance(issue, str) else issue) - {"none"}
        unknown = issues - set(ISSUES)
        if unknown:
            raise ValueError(f"unknown issue(s): {sorted(unknown)}; known: {ISSUES}")
        drivetrain = drivetrain.upper()
        if drivetrain not in DRIVETRAINS:
            raise ValueError(f"drivetrain must be one of {DRIVETRAINS}")
        self.issues = issues
        self.drivetrain = drivetrain
        self.seed = seed
        self.severity = severity
        self.hz = hz
        self.start_time = start_time
        self.car_ordinal = car_ordinal
        self.track_ordinal = track_ordinal
        self.gears = CAR.gears
        self.final_drive = final_drive_for(drivetrain, 0.93)
        if "gearing-short" in issues:
            # limiter speed in top gear 6 % below the clean lap's top speed
            self.final_drive = final_drive_for(drivetrain, 1.0 / 0.94)
        elif "gearing-long" in issues:
            # an overdrive top gear: the car reaches it but ends the straight at ~70 % rpm
            self.gears = (*CAR.gears[:-1], 0.80)
        omega = CAR.max_rpm / CAR.rpm_factor(self.final_drive)
        self.v_cap = omega / self.gears[-1]
        self._frame_index = 0
        self._lap_start = 0.0
        self._lap_index = 0
        self._distance = 0.0
        self._best = 0.0
        self._last = 0.0
        self._temps = [175.0, 175.0, 172.0, 172.0]
        self._wear = [0.0, 0.0, 0.0, 0.0]
        self._fuel = 1.0

    @property
    def laps_done(self) -> int:
        return self._lap_index

    def laps(self, count: int) -> list[list[Frame]]:
        return [self.lap() for _ in range(count)]

    def frames(self) -> Iterator[Frame]:
        """Endless stream of frames, lap after lap."""
        while True:
            yield from self.lap()

    def lap(self) -> list[Frame]:
        """Generate the next lap (continuous with the previous one)."""
        lap_seed = (self.seed * 1_000_003 + self._lap_index) * 2
        rng = random.Random(lap_seed)
        # the driver's pace has its own stream, so it doesn't depend on the issues
        pace = 1.0 + random.Random(lap_seed + 1).gauss(0.0, 0.003)
        trk = track()
        n = len(trk.kappa)
        base = _profile(trk, CAR, self.drivetrain, 1.0, [1.0] * n, self.v_cap)
        plan = _plan(self.issues, trk, base, self.drivetrain, rng, self.severity)
        prof = _profile(trk, CAR, self.drivetrain, pace, plan.grip, self.v_cap)
        frames = self._frames(trk, prof, plan, rng)
        lap_time = prof.t[-1]
        self._lap_start += lap_time
        self._distance += trk.length
        self._last = lap_time
        self._best = lap_time if not self._best else min(self._best, lap_time)
        self._lap_index += 1
        return frames

    def _frames(self, trk: Track, prof: _Profile, plan: _Plan, rng: random.Random) -> list[Frame]:
        car, dt_frame, n = CAR, 1.0 / self.hz, len(trk.kappa)
        t_grid, lap_time = prof.t, prof.t[-1]
        gauss = rng.gauss
        trac = car.traction(self.drivetrain)
        rpm_k = car.rpm_factor(self.final_drive)
        shift_rpm = car.shift_pct * car.max_rpm
        tau_temp = 20.0
        out: list[Frame] = []
        k = self._frame_index
        while True:
            tg = k / self.hz
            tau = tg - self._lap_start
            if tau >= lap_time:
                break
            if tau < 0:
                k += 1
                continue
            i = min(n - 1, bisect_right(t_grid, tau) - 1)
            w = (tau - t_grid[i]) / (t_grid[i + 1] - t_grid[i])
            j = i if w < 0.5 else (i + 1) % n
            i1 = (i + 1) % n
            v = prof.v[i] + (prof.v[i1] - prof.v[i]) * w
            kap = trk.kappa[j]
            sign = 1 if kap >= 0 else -1
            thr, brk = prof.throttle[j], prof.brake[j]

            a_lat = v * v * kap
            alat_phys = G * (car.mu_lat + car.aero_lat * v * v)
            u = min(1.2, abs(a_lat) / alat_phys)
            steer = kap * (car.wheelbase + car.us_gradient * v * v) / car.steer_lock
            steer = steer * plan.steer_mul[j] + gauss(0, 0.004)
            yaw_rate = v * kap + sign * plan.d_yaw[j] + gauss(0, 0.004)

            sa_f = max(0.0, 0.86 * u + 0.04 * brk * u + plan.d_sa_f[j] + gauss(0, 0.02))
            sa_r = max(0.0, 0.83 * u + 0.08 * brk * u + plan.d_sa_r[j] + gauss(0, 0.02))
            out_f, in_f = sa_f * 1.06 * sign, sa_f * 0.94 * sign
            out_r, in_r = sa_r * 1.06 * sign, sa_r * 0.94 * sign
            sa = (out_f, in_f, out_r, in_r) if sign > 0 else (in_f, out_f, in_r, out_r)

            a_full = min(trac, car.power / max(v, 1.0)) - car.drag * v * v
            drive = (0.02 + 0.32 * thr * max(0.0, min(1.0, a_full / trac))) if thr > 0 else 0.0
            sr_f, sr_r = -0.5 * brk, -0.45 * brk
            if brk > 0.6:
                # ABS cycling as seen on real recordings: slip ratio dips past -1 for
                # ~0.1 s at a time (deep enough to fool a "slip ratio < -1" rule), but
                # the wheels keep turning at ~80 % of road speed
                sr_f -= 1.1 * brk * max(0.0, math.sin(2 * math.pi * _ABS_HZ * tg)) ** 2
                sr_r -= 0.8 * brk * max(0.0, math.sin(2 * math.pi * _ABS_HZ * tg + 2.0)) ** 2
            if self.drivetrain == "FWD":
                sr_f += drive
            elif self.drivetrain == "RWD":
                sr_r += drive
            else:
                sr_f += 0.6 * drive
                sr_r += 0.8 * drive
            sr_f += plan.d_sr_f[j]
            sr_r += plan.d_sr_r[j]
            if plan.lock_f[j]:
                sr_f = _LOCKED_SLIP_RATIO
            if plan.lock_r[j]:
                sr_r = _LOCKED_SLIP_RATIO
            sr = (
                sr_f + gauss(0, 0.015),
                sr_f + gauss(0, 0.015),
                sr_r + gauss(0, 0.015),
                sr_r + gauss(0, 0.015),
            )

            s_pos = (i + w) * _DS
            base_travel = 0.42 + 0.20 * (v / 85.0) ** 2
            road = 0.012 * math.sin(s_pos * 0.37) + gauss(0, 0.006)
            lt = 0.07 * min(2.0, abs(a_lat) / G) * sign
            ft = (
                base_travel + 0.07 * brk - 0.03 * thr + plan.d_susp_f[j] + plan.susp_offset_f + road
            )
            rt = (
                base_travel - 0.04 * brk + 0.04 * thr + plan.d_susp_r[j] + plan.susp_offset_r + road
            )
            susp = tuple(min(1.0, max(0.0, x)) for x in (ft + lt, ft - lt, rt + lt, rt - lt))

            gear = len(self.gears)
            rpm = v * self.gears[-1] * rpm_k
            for g, ratio in enumerate(self.gears, start=1):
                r = v * ratio * rpm_k
                if r <= shift_rpm:
                    gear, rpm = g, r
                    break
            if prof.limiter[j] and thr >= 0.95:
                rpm = car.max_rpm * (0.992 + 0.005 * math.sin(tg * 50.0))
            rpm = max(car.idle_rpm, min(car.max_rpm, rpm))

            temps = self._temps
            for q in range(4):
                use = min(1.6, math.hypot(abs(sa[q]), 0.8 * abs(sr[q])))
                temps[q] += (150.0 + 60.0 * use - temps[q]) * dt_frame / tau_temp
                self._wear[q] += 0.00006 * use * dt_frame
            self._fuel = max(0.0, self._fuel - 0.0002 * dt_frame)

            heading = trk.heading[i] + (trk.heading[i + 1] - trk.heading[i]) * w
            px = trk.x[i] + (trk.x[i + 1] - trk.x[i]) * w
            pz = trk.z[i] + (trk.z[i + 1] - trk.z[i]) * w
            a_lon = prof.a_lon[j]
            out.append(
                Frame(
                    recv_time=self.start_time + tg,
                    is_race_on=True,
                    timestamp_ms=round(math.floor(tg * 64) * 15.625) % _TS_MOD,
                    engine_max_rpm=car.max_rpm,
                    engine_idle_rpm=car.idle_rpm,
                    current_engine_rpm=rpm,
                    accel_x=a_lat + gauss(0, 0.15),
                    accel_y=gauss(0, 0.1),
                    accel_z=a_lon + gauss(0, 0.15),
                    vel_x=v * 0.02 * u * sign,
                    vel_y=0.0,
                    vel_z=v,
                    ang_vel_x=gauss(0, 0.01),
                    ang_vel_y=yaw_rate,
                    ang_vel_z=gauss(0, 0.01),
                    yaw=heading,
                    pitch=-0.004 * a_lon / G,
                    roll=0.02 * a_lat / G,
                    susp_travel_norm=Corners(*susp),
                    tire_slip_ratio=Corners(*sr),
                    wheel_rot_speed=Corners(
                        *(
                            v / radius * max(0.0, 1.0 + _SLIP_PER_UNIT * x)
                            for radius, x in zip(car.wheel_radii, sr, strict=True)
                        )
                    ),
                    wheel_on_rumble=Corners(0.0, 0.0, 0.0, 0.0),
                    wheel_in_puddle=Corners(0.0, 0.0, 0.0, 0.0),
                    surface_rumble=Corners(0.0, 0.0, 0.0, 0.0),
                    tire_slip_angle=Corners(*sa),
                    tire_combined_slip=Corners(*map(math.hypot, sa, sr)),
                    susp_travel_m=Corners(*(0.12 * x for x in susp)),
                    car_ordinal=self.car_ordinal,
                    car_class=4,
                    car_pi=800,
                    drivetrain=DRIVETRAINS.index(self.drivetrain),
                    num_cylinders=8,
                    pos_x=px,
                    pos_y=0.0,
                    pos_z=pz,
                    speed=v,
                    power=max(0.0, thr * car.power * 1400.0 * rpm / car.max_rpm),
                    torque=max(0.0, thr * 600.0),
                    tire_temp=Corners(*temps),
                    boost=0.0,
                    fuel=self._fuel,
                    distance_traveled=self._distance + s_pos,
                    best_lap=self._best,
                    last_lap=self._last,
                    current_lap=tau,
                    current_race_time=tg,
                    lap_number=self._lap_index,
                    race_position=1,
                    throttle=round(thr * 255),
                    brake=round(brk * 255),
                    clutch=0,
                    handbrake=0,
                    gear=gear,
                    steer=max(-127, min(127, round(steer * 127))),
                    driving_line=0,
                    ai_brake_diff=0,
                    tire_wear=Corners(*self._wear),
                    track_ordinal=self.track_ordinal,
                )
            )
            k += 1
        self._frame_index = k
        return out


def generate_lap(
    issue: str | Iterable[str] = "none",
    *,
    drivetrain: str = "RWD",
    seed: int = 0,
    severity: float = 1.0,
    hz: float = 60.0,
) -> list[Frame]:
    """One flying lap (starts and ends on the start/finish line at speed)."""
    return SyntheticDriver(issue, drivetrain=drivetrain, seed=seed, severity=severity, hz=hz).lap()


def generate_laps(
    issue: str | Iterable[str] = "none",
    laps: int = 3,
    *,
    drivetrain: str = "RWD",
    seed: int = 0,
    severity: float = 1.0,
    hz: float = 60.0,
) -> list[list[Frame]]:
    """Consecutive flying laps of one continuous stint."""
    driver = SyntheticDriver(issue, drivetrain=drivetrain, seed=seed, severity=severity, hz=hz)
    return driver.laps(laps)
