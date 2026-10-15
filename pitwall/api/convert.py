"""Shape internal records and frames into API payloads (canonical units)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from pitwall.telemetry import canonical as cu
from pitwall.telemetry.model import Frame

_INTERNAL_SESSION_FIELDS = ("raw_file", "frame_count")
_INTERNAL_LAP_FIELDS = ("first_frame", "last_frame")


def public_session(session: dict[str, Any], *, recording_id: int | None) -> dict[str, Any]:
    out = {k: v for k, v in session.items() if k not in _INTERNAL_SESSION_FIELDS}
    out["recording"] = recording_id is not None and session["id"] == recording_id
    return out


def public_lap(lap: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in lap.items() if k not in _INTERNAL_LAP_FIELDS}


def car_status(frame: Frame | None, info: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The car on track; ``info`` (name/division) comes from the baselines module."""
    if frame is None or frame.car_ordinal == 0:
        return None
    return {
        "ordinal": frame.car_ordinal,
        "name": (info or {}).get("name"),
        "division": (info or {}).get("division"),
        "class": frame.car_class,
        "class_name": cu.class_name(frame.car_pi),
        "pi": frame.car_pi,
        "drivetrain": cu.drivetrain_name(frame.drivetrain),
    }


def telemetry_message(frame: Frame, t: float) -> dict[str, Any]:
    return {
        "type": "telemetry",
        "t": round(t, 3),
        "speed": round(frame.speed, 3),
        "rpm": round(frame.current_engine_rpm, 1),
        "max_rpm": round(frame.engine_max_rpm, 1),
        "gear": cu.gear(frame.gear),
        "throttle": round(cu.pedal(frame.throttle), 3),
        "brake": round(cu.pedal(frame.brake), 3),
        "steer": round(cu.steer(frame.steer), 3),
        "lap_number": frame.lap_number + 1,
        "current_lap": round(frame.current_lap, 3),
        "last_lap": cu.lap_time(frame.last_lap),
        "best_lap": cu.lap_time(frame.best_lap),
        "race_position": frame.race_position,
        "lat_g": round(cu.lat_g(frame), 3),
        "lon_g": round(cu.lon_g(frame), 3),
        "tire_temp": cu.corners_c(frame.tire_temp),
        "tire_wear": cu.corners(frame.tire_wear),
        "slip_angle": cu.corners(frame.tire_slip_angle),
        "slip_ratio": cu.corners(frame.tire_slip_ratio),
        "susp": cu.corners(frame.susp_travel_norm),
        "pos": {"x": round(frame.pos_x, 2), "z": round(frame.pos_z, 2)},
    }


# --- lap trace ---------------------------------------------------------------

_TRACE_CHANNELS: dict[str, Callable[[Frame], float]] = {
    "speed": lambda f: f.speed,
    "throttle": lambda f: cu.pedal(f.throttle),
    "brake": lambda f: cu.pedal(f.brake),
    "steer": lambda f: cu.steer(f.steer),
    "rpm": lambda f: f.current_engine_rpm,
    "lat_g": cu.lat_g,
    "lon_g": cu.lon_g,
    "slip_angle_front": lambda f: (abs(f.tire_slip_angle.fl) + abs(f.tire_slip_angle.fr)) / 2,
    "slip_angle_rear": lambda f: (abs(f.tire_slip_angle.rl) + abs(f.tire_slip_angle.rr)) / 2,
    "slip_ratio_rear": lambda f: (abs(f.tire_slip_ratio.rl) + abs(f.tire_slip_ratio.rr)) / 2,
    "susp_front": lambda f: f.susp_travel_norm.front,
    "susp_rear": lambda f: f.susp_travel_norm.rear,
    "pos_x": lambda f: f.pos_x,
    "pos_z": lambda f: f.pos_z,
}
TRACE_KEYS = ("hz", "t", "distance", *list(_TRACE_CHANNELS)[:4], "gear", *list(_TRACE_CHANNELS)[4:])


def frame_times(frames: Sequence[Frame]) -> list[float]:
    """Non-decreasing time axis for a lap, from the game's lap timer.

    ``current_lap`` advances with every packet whatever the packet rate (unlike
    ``timestamp_ms``, which ticks at 60 Hz and repeats on PC). Steps backwards
    (rewinds) count as zero, so the axis never goes back.
    """
    if not frames:
        return []
    times = [frames[0].current_lap]
    for prev, cur in zip(frames, frames[1:], strict=False):
        times.append(times[-1] + max(0.0, cur.current_lap - prev.current_lap))
    return times


def build_trace(frames: Sequence[Frame], hz: float) -> dict[str, Any]:
    """Resample a lap to ``hz`` samples per second (parallel arrays)."""
    out: dict[str, Any] = {key: [] for key in TRACE_KEYS}
    out["hz"] = int(hz) if float(hz).is_integer() else hz
    if not frames:
        return out
    times = frame_times(frames)
    d0 = frames[0].distance_traveled
    step = 1.0 / hz
    n = int((times[-1] - times[0]) / step) + 1
    i = 0
    for k in range(n):
        t = times[0] + k * step
        while i < len(times) - 2 and times[i + 1] <= t:
            i += 1
        a, b = frames[i], frames[min(i + 1, len(frames) - 1)]
        span = times[min(i + 1, len(times) - 1)] - times[i]
        w = 0.0 if span <= 0 else min(1.0, max(0.0, (t - times[i]) / span))

        def lerp(fn: Callable[[Frame], float], a: Frame = a, b: Frame = b, w: float = w) -> float:
            return fn(a) + (fn(b) - fn(a)) * w

        out["t"].append(round(t, 3))
        out["distance"].append(round(lerp(lambda f: f.distance_traveled) - d0, 2))
        out["gear"].append(cu.gear(a.gear))
        for key, fn in _TRACE_CHANNELS.items():
            out[key].append(round(lerp(fn), 4))
    return out
