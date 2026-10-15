"""Frame -> Sample conversion: time base, distance, units and light smoothing.

A :class:`Sample` is the compact per-frame record every other analysis module
works on. :class:`SampleBuilder` is streaming, so the per-lap analyzer and the
live analyzer share exactly the same conditioning.

Time base. The PC game sends 120-160 packets/s. ``CurrentRaceTime`` and
``CurrentLap`` advance in steps of 1/360 s with every packet, while
``TimestampMS`` only ticks every ~15.6 ms (about half the packets repeat it).
Time comes from the race clock, then the lap timer, then the receive time, then
the timestamp (a repeated timestamp is a zero step), then the last good step.
Nothing downstream counts frames: windows, durations and averages use seconds.

Discontinuities. A rewind steps the race clock back a few seconds and a
restart resets it. The first sample after one has ``cut`` set: no time is
added for the jump, the smoothing window restarts, distance follows the car
back to where the rewind put it, and consumers close their open segments
(:meth:`Segmenter.flush` then ``reset``) before taking the sample.

Smoothing is a centred moving average over ``SMOOTH_WINDOW_S``, so samples
come out half a window late; call :meth:`SampleBuilder.flush` at the end of a
lap.

Wheel speed. Each wheel's rolling radius is learned from free-rolling samples
(road speed / wheel rotation speed), which turns ``WheelRotationSpeed`` into a
wheel-speed ratio (1.0 = rolling, 0.0 = stopped). That is what tells a locked
wheel from an ABS-modulated one.
"""

from __future__ import annotations

from collections import deque

from pitwall.telemetry.model import Frame

from .thresholds import (
    DEFAULT_DT_S,
    JUMP_GAP_S,
    MAX_FRAME_GAP_S,
    RADIUS_KEEP,
    RADIUS_MAX_SLIP_ANGLE,
    RADIUS_MAX_SLIP_RATIO,
    RADIUS_MIN_SAMPLES,
    RADIUS_MIN_SPEED,
    REWIND_MIN_S,
    SMOOTH_WINDOW_S,
    WHEEL_LOADED_TRAVEL,
    G,
)

_TS_MOD = 1 << 32
_HALF = SMOOTH_WINDOW_S / 2
_RADIUS_REFRESH = 25  # recompute the median radius every N new estimates


class Sample:
    """One frame in analysis units (s, m, m/s, g, rad/s, pedals 0..1, steer -1..1)."""

    __slots__ = (
        "i", "t", "dt", "dist", "v", "thr", "brk", "steer", "gear", "rpm_pct",
        "lat_g", "lon_g", "yaw", "sa_f", "sa_r", "sr_f_max", "sr_f_min", "sr_r_max",
        "sr_r_min", "ws_f", "ws_r", "susp_f", "susp_r", "rumble_f", "rumble_r", "temps",
        "wear", "lap", "power", "cut",
    )  # fmt: skip

    def __init__(self) -> None:  # fields are filled by SampleBuilder
        pass


def f_to_c(value: float) -> float:
    return (value - 32.0) * 5.0 / 9.0


class _Radius:
    """Rolling-radius estimate for one wheel (median of recent free-rolling samples)."""

    __slots__ = ("values", "added", "radius")

    def __init__(self) -> None:
        self.values: deque[float] = deque(maxlen=RADIUS_KEEP)
        self.added = 0
        self.radius: float | None = None

    def add(self, r: float) -> None:
        self.values.append(r)
        self.added += 1
        if self.added >= RADIUS_MIN_SAMPLES and (
            self.radius is None or self.added % _RADIUS_REFRESH == 0
        ):
            ordered = sorted(self.values)
            self.radius = ordered[len(ordered) // 2]


_NOTHING: tuple[Sample, ...] = ()


class SampleBuilder:
    """Turns a stream of frames into a stream of smoothed samples."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._count = 0
        self._prev: Frame | None = None
        self._last_dt = DEFAULT_DT_S
        self._prev_v = 0.0
        self._t = 0.0
        self._dist = 0.0
        self._pending: deque[Sample] = deque()
        self._ahead: deque[tuple[float, float, float, float, float]] = deque()
        self._inwin: deque[tuple[float, float, float, float, float]] = deque()
        self._sums = [0.0, 0.0, 0.0, 0.0]
        self._radius = (_Radius(), _Radius(), _Radius(), _Radius())

    @property
    def wheel_radii(self) -> tuple[float | None, ...]:
        return tuple(r.radius for r in self._radius)

    def push(self, frame: Frame) -> tuple[Sample, ...] | list[Sample]:
        """Add a frame; return the samples that just became fully smoothed (usually one)."""
        s = self._convert(frame)
        lead: list[Sample] | None = None
        if s.cut:  # never smooth across a rewind: emit what came before it first
            lead = self.flush()
            self._inwin.clear()
            self._sums = [0.0, 0.0, 0.0, 0.0]
        self._pending.append(s)
        self._ahead.append((s.t, s.lat_g, s.lon_g, s.yaw, s.steer))
        newest = s.t
        if newest - self._pending[0].t < _HALF:
            return lead or _NOTHING
        out = lead or []
        out.append(self._emit())
        while self._pending and newest - self._pending[0].t >= _HALF:
            out.append(self._emit())
        return out

    def flush(self) -> list[Sample]:
        """Emit the samples still waiting for their right-hand smoothing neighbours."""
        out = []
        while self._pending:
            out.append(self._emit())
        return out

    def _emit(self) -> Sample:
        p = self._pending.popleft()
        sums, ahead, inwin = self._sums, self._ahead, self._inwin
        right, left = p.t + _HALF, p.t - _HALF
        while ahead and ahead[0][0] <= right:
            raw = ahead.popleft()
            inwin.append(raw)
            sums[0] += raw[1]
            sums[1] += raw[2]
            sums[2] += raw[3]
            sums[3] += raw[4]
        while inwin and inwin[0][0] < left:
            raw = inwin.popleft()
            sums[0] -= raw[1]
            sums[1] -= raw[2]
            sums[2] -= raw[3]
            sums[3] -= raw[4]
        n = len(inwin)
        p.lat_g = sums[0] / n
        p.lon_g = sums[1] / n
        p.yaw = sums[2] / n
        p.steer = sums[3] / n
        return p

    def _step(self, f: Frame, prev: Frame) -> tuple[float, bool]:
        """Time step to ``f`` and whether the data is discontinuous there."""
        d = f.current_race_time - prev.current_race_time
        if 0.0 < d <= MAX_FRAME_GAP_S:
            return d, False
        if d < -REWIND_MIN_S or d > JUMP_GAP_S:
            return self._last_dt, True  # rewind, restart or dropout
        # no race clock (it stays 0 outside races): the lap timer has the same steps
        if f.lap_number == prev.lap_number:
            d = f.current_lap - prev.current_lap
            if 0.0 < d <= MAX_FRAME_GAP_S:
                return d, False
            if d < -REWIND_MIN_S or d > JUMP_GAP_S:
                return self._last_dt, True
        elif f.lap_number < prev.lap_number:
            return self._last_dt, True  # rewound into the previous lap
        d = f.recv_time - prev.recv_time
        if 0.0 < d <= MAX_FRAME_GAP_S:
            return d, False
        # TimestampMS only ticks every ~15.6 ms: a repeated value shares the tick (dt 0),
        # mixing it with another clock would count the same time twice
        d = ((f.timestamp_ms - prev.timestamp_ms) % _TS_MOD) / 1000.0
        if d <= MAX_FRAME_GAP_S:
            return d, False
        return self._last_dt, False

    def _convert(self, f: Frame) -> Sample:
        prev = self._prev
        cut = False
        v = f.speed
        if prev is None:
            dt = self._last_dt
        else:
            dt, cut = self._step(f, prev)
            self._t += dt
            if cut:
                # a rewind puts the car back on track: follow it (never below 0)
                back = f.distance_traveled - prev.distance_traveled
                if back < 0.0:
                    self._dist = max(0.0, self._dist + back)
            else:
                self._dist += 0.5 * (v + self._prev_v) * dt
        self._prev = f
        self._last_dt = dt
        self._prev_v = v

        s = Sample()
        s.i = self._count
        self._count += 1
        s.t = self._t
        s.dt = dt
        s.dist = self._dist
        s.v = v
        s.thr = f.throttle / 255.0
        s.brk = f.brake / 255.0
        steer = f.steer / 127.0
        s.steer = -1.0 if steer < -1.0 else (1.0 if steer > 1.0 else steer)
        s.gear = f.gear
        s.rpm_pct = f.current_engine_rpm / f.engine_max_rpm if f.engine_max_rpm > 0 else 0.0
        s.lat_g = f.accel_x / G
        s.lon_g = f.accel_z / G
        s.yaw = f.ang_vel_y
        sa = f.tire_slip_angle
        s.sa_f = (abs(sa[0]) + abs(sa[1])) * 0.5
        s.sa_r = (abs(sa[2]) + abs(sa[3])) * 0.5
        sr = f.tire_slip_ratio
        s.sr_f_max = sr[0] if sr[0] > sr[1] else sr[1]
        s.sr_r_max = sr[2] if sr[2] > sr[3] else sr[3]
        susp = f.susp_travel_norm
        s.susp_f = susp[0] if susp[0] > susp[1] else susp[1]
        s.susp_r = susp[2] if susp[2] > susp[3] else susp[3]
        rumble = f.wheel_on_rumble
        s.rumble_f = rumble[0] > 0 or rumble[1] > 0
        s.rumble_r = rumble[2] > 0 or rumble[3] > 0
        s.temps = f.tire_temp
        s.wear = f.tire_wear
        s.lap = f.lap_number
        s.power = f.power
        s.cut = cut
        self._wheels(s, f, sa, sr, susp)
        return s

    def _wheels(self, s: Sample, f: Frame, sa, sr, susp) -> None:  # type: ignore[no-untyped-def]
        """Per-axle lock signals from loaded wheels only (a wheel in the air can stop freely)."""
        v = s.v
        omega = f.wheel_rot_speed
        free = v >= RADIUS_MIN_SPEED and s.brk < 0.05
        sr_min = [0.0, 0.0]
        ws_min: list[float | None] = [None, None]
        for k in range(4):
            if susp[k] < WHEEL_LOADED_TRAVEL:
                continue
            axle = k >> 1
            if sr[k] < sr_min[axle]:
                sr_min[axle] = sr[k]
            w = abs(omega[k])
            est = self._radius[k]
            if (
                free
                and w > 1.0
                and -RADIUS_MAX_SLIP_RATIO <= sr[k] <= RADIUS_MAX_SLIP_RATIO
                and abs(sa[k]) <= RADIUS_MAX_SLIP_ANGLE
            ):
                est.add(v / w)
            if est.radius is not None and v > 5.0:
                ratio = w * est.radius / v
                cur = ws_min[axle]
                if cur is None or ratio < cur:
                    ws_min[axle] = ratio
        s.sr_f_min, s.sr_r_min = sr_min
        s.ws_f, s.ws_r = ws_min
