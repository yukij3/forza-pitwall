"""Frame -> Sample conversion: time base, distance, units and light smoothing.

A :class:`Sample` is the compact per-frame record every other analysis module
works on. :class:`SampleBuilder` is streaming (one frame in, at most one sample
out) so the per-lap analyzer and the live analyzer share exactly the same
conditioning. Smoothing is a centred moving average, so samples come out
``SMOOTH_SAMPLES // 2`` frames late; call :meth:`SampleBuilder.flush` at the
end of a lap.
"""

from __future__ import annotations

from collections import deque

from pitwall.telemetry.model import Frame

from .thresholds import DEFAULT_DT_S, MAX_FRAME_GAP_S, SMOOTH_SAMPLES, G

_TS_MOD = 1 << 32


class Sample:
    """One frame in analysis units (s, m, m/s, g, rad/s, pedals 0..1, steer -1..1)."""

    __slots__ = (
        "i", "t", "dt", "dist", "v", "thr", "brk", "steer", "gear", "rpm_pct",
        "lat_g", "lon_g", "yaw", "sa_f", "sa_r", "sr_f_max", "sr_f_min", "sr_r_max",
        "sr_r_min", "susp_f", "susp_r", "rumble_f", "rumble_r", "temps", "wear", "lap",
    )  # fmt: skip

    def __init__(self) -> None:  # fields are filled by SampleBuilder
        pass


def f_to_c(value: float) -> float:
    return (value - 32.0) * 5.0 / 9.0


class SampleBuilder:
    """Turns a stream of frames into a stream of smoothed samples."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._count = 0
        self._prev_ts: int | None = None
        self._prev_recv: float | None = None
        self._prev_v = 0.0
        self._t = 0.0
        self._dist = 0.0
        self._half = SMOOTH_SAMPLES // 2
        self._win: deque[Sample] = deque(maxlen=SMOOTH_SAMPLES)
        self._raw: deque[tuple[float, float, float, float]] = deque(maxlen=SMOOTH_SAMPLES)
        self._emitted = 0

    def push(self, frame: Frame) -> Sample | None:
        """Add a frame; return the sample that just became fully smoothed, if any."""
        s = self._convert(frame)
        self._win.append(s)
        self._raw.append((s.lat_g, s.lon_g, s.yaw, s.steer))
        if self._count - self._emitted > self._half:
            return self._emit(len(self._win) - 1 - self._half)
        return None

    def flush(self) -> list[Sample]:
        """Emit the samples still waiting for their right-hand smoothing neighbours."""
        out = []
        pending = self._count - self._emitted
        for k in range(pending, 0, -1):
            out.append(self._emit(len(self._win) - k))
        return out

    def _emit(self, pos: int) -> Sample:
        lo = max(0, pos - self._half)
        hi = min(len(self._raw), pos + self._half + 1)
        n = hi - lo
        lat = lon = yaw = steer = 0.0
        for k in range(lo, hi):
            a, b, c, d = self._raw[k]
            lat += a
            lon += b
            yaw += c
            steer += d
        s = self._win[pos]
        s.lat_g = lat / n
        s.lon_g = lon / n
        s.yaw = yaw / n
        s.steer = steer / n
        self._emitted += 1
        return s

    def _convert(self, f: Frame) -> Sample:
        dt = DEFAULT_DT_S
        if self._prev_ts is not None:
            d = ((f.timestamp_ms - self._prev_ts) % _TS_MOD) / 1000.0
            if 0.0 < d <= MAX_FRAME_GAP_S:
                dt = d
            elif self._prev_recv is not None:
                d = f.recv_time - self._prev_recv
                if 0.0 < d <= MAX_FRAME_GAP_S:
                    dt = d
        first = self._prev_ts is None
        self._prev_ts = f.timestamp_ms
        self._prev_recv = f.recv_time

        v = f.speed
        if not first:
            self._t += dt
            self._dist += 0.5 * (v + self._prev_v) * dt
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
        fl, fr, rl, rr = f.tire_slip_angle
        s.sa_f = (abs(fl) + abs(fr)) * 0.5
        s.sa_r = (abs(rl) + abs(rr)) * 0.5
        fl, fr, rl, rr = f.tire_slip_ratio
        s.sr_f_max = fl if fl > fr else fr
        s.sr_f_min = fr if fl > fr else fl
        s.sr_r_max = rl if rl > rr else rr
        s.sr_r_min = rr if rl > rr else rl
        fl, fr, rl, rr = f.susp_travel_norm
        s.susp_f = fl if fl > fr else fr
        s.susp_r = rl if rl > rr else rr
        fl, fr, rl, rr = f.wheel_on_rumble
        s.rumble_f = fl > 0 or fr > 0
        s.rumble_r = rl > 0 or rr > 0
        s.temps = f.tire_temp
        s.wear = f.tire_wear
        s.lap = f.lap_number
        return s
