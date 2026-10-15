"""Synthetic Data Out source: a car lapping a closed track at 60 Hz.

The track is two identical halves (straights, a slow 90-degree corner, a
chicane and a fast sweeper), so it closes on itself. A speed profile limited by
lateral grip, braking and power drives the car; inputs, gear, rpm, slip, tire
temperatures and wear are derived from it. ``issue`` injects one handling
problem so the analysis has something to find.

:func:`simulate_frames` is the frame source; :func:`send` paces any frame
iterable over UDP, so another generator can be swapped in.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

from pitwall.telemetry.model import Corners, Drivetrain, Frame
from pitwall.telemetry.packet import RAW_GEAR_NEUTRAL, blank_frame, encode, raw_gear
from pitwall.tools.udp import pace

ISSUES = ("none", "understeer", "oversteer-exit", "wheelspin", "lockup-rear", "bottoming")

HZ = 60
DT = 1.0 / HZ
G = 9.81

# Car (fictional ordinals: the simulator is not a real car or track)
SIM_CAR_ORDINAL = 90001
SIM_TRACK_ORDINAL = 90001
SIM_CAR_PI = 812
SIM_CAR_CLASS = 6  # FM2023 index for class R
MAX_RPM = 8500.0
IDLE_RPM = 900.0
WHEEL_RADIUS = 0.33
FINAL_DRIVE = 3.5
GEAR_RATIOS = (3.2, 2.35, 1.85, 1.5, 1.24, 1.04)
UPSHIFT_RPM = 8100.0
DOWNSHIFT_RPM = 4700.0
PEAK_POWER_W = 450_000.0

# Grip and performance
A_LAT = 14.0  # m/s^2 lateral limit
A_BRAKE = 13.0  # m/s^2 braking limit
A_ACCEL = 9.0  # m/s^2 traction-limited acceleration at low speed
V_TOP = 78.0  # m/s

# Track: half a lap; the second half repeats it (central symmetry closes the loop).
# ("S", length_m) or ("C", radius_m, angle_deg); positive angles turn right.
HALF_TRACK: tuple[tuple[float, ...], ...] = (
    ("S", 700.0),
    ("C", 45.0, 90.0),
    ("S", 250.0),
    ("C", 60.0, -40.0),
    ("C", 60.0, 40.0),
    ("S", 150.0),
    ("C", 150.0, 90.0),
)


@dataclass(frozen=True, slots=True)
class SimOptions:
    laps: int = 5  # line crossings to drive; 0 = endless
    issue: str = "none"
    seed: int = 1
    tail_s: float = 2.0  # driving after the last crossing, then race-off
    menu_s: float = 1.0  # race-off packets at the end


FrameSource = Callable[[SimOptions], Iterator[Frame]]


EXIT_ZONE_M = 60  # throttle within this distance after a corner counts as its exit


@dataclass(frozen=True, slots=True)
class Track:
    x: list[float]
    z: list[float]
    heading: list[float]
    curvature: list[float]  # 1/m, positive = right turn, per metre of track
    turn_sign: list[float]  # direction of the current or most recent corner: +1 right, -1 left
    exit_zone: list[bool]  # in a corner or just after one

    @property
    def length(self) -> int:
        return len(self.curvature)


def build_track() -> Track:
    curvature: list[float] = []
    for _ in range(2):
        for seg in HALF_TRACK:
            if seg[0] == "S":
                curvature += [0.0] * round(seg[1])
            else:
                radius, angle = seg[1], math.radians(seg[2])
                metres = round(radius * abs(angle))
                curvature += [angle / metres] * metres  # exact total heading change
    x, z, heading = [0.0], [0.0], [0.0]
    for k in curvature[:-1]:
        mid = heading[-1] + k / 2
        x.append(x[-1] + math.sin(mid))
        z.append(z[-1] + math.cos(mid))
        heading.append(heading[-1] + k)
    n = len(curvature)
    turn_sign, exit_zone = [1.0] * n, [False] * n
    sign, since = 1.0, EXIT_ZONE_M + 1
    for i in range(2 * n):  # twice, so the zone wraps across the line
        k = curvature[i % n]
        if k:
            sign, since = math.copysign(1.0, k), 0
        else:
            since += 1
        turn_sign[i % n] = sign
        exit_zone[i % n] = since <= EXIT_ZONE_M
    return Track(
        x=x, z=z, heading=heading, curvature=curvature, turn_sign=turn_sign, exit_zone=exit_zone
    )


def speed_profile(track: Track) -> list[float]:
    """Fastest speed at each metre given grip, braking and acceleration limits."""
    n = track.length
    limit = [min(V_TOP, math.sqrt(A_LAT / abs(k))) if k else V_TOP for k in track.curvature]
    v = limit[:]
    for _ in range(2):  # loop twice so the wrap-around settles
        for i in range(1, n + 1):
            prev, cur = v[(i - 1) % n], i % n
            v[cur] = min(v[cur], math.sqrt(prev**2 + 2 * _accel(prev)))
        for i in range(n - 1, -1, -1):
            nxt = v[(i + 1) % n]
            v[i] = min(v[i], math.sqrt(nxt**2 + 2 * A_BRAKE))
    return v


def _accel(v: float) -> float:
    return A_ACCEL * max(0.0, 1.0 - (v / V_TOP) ** 2)


def _rpm(v: float, gear: int) -> float:
    return v / WHEEL_RADIUS * GEAR_RATIOS[gear - 1] * FINAL_DRIVE * 60.0 / (2 * math.pi)


def _approach(current: float, target: float, rate: float) -> float:
    return current + max(-rate, min(rate, target - current))


def simulate_frames(opts: SimOptions | None = None) -> Iterator[Frame]:
    """Yield 60 Hz frames; ``recv_time`` is simulated seconds from 0."""
    opts = opts or SimOptions()
    if opts.issue not in ISSUES:
        raise ValueError(f"unknown issue {opts.issue!r}; choose from {', '.join(ISSUES)}")
    rng = random.Random(opts.seed)
    track = build_track()
    profile = speed_profile(track)
    n = track.length
    issue = opts.issue

    s = v = t = lap_time = distance = 0.0
    lap = 0
    last_lap = best_lap = 0.0
    gear = 1
    throttle = brake = 0.0
    temps = [120.0, 120.0, 120.0, 120.0]  # degF
    wear = [1.0, 1.0, 1.0, 1.0]
    fuel = 1.0
    pace_factor = 0.99
    tail_left: float | None = None

    while True:
        # --- driver: follow the speed profile -------------------------------
        look = int(s + v * DT + 1) % n
        target = profile[look] * pace_factor
        cruise = 0.35 + 0.3 * (v / V_TOP)  # throttle that holds a steady speed
        flat_out = v + _accel(v) * DT
        if target >= flat_out:  # power-limited: full throttle
            v_new, want_throttle, want_brake = flat_out, 1.0, 0.0
        elif target >= v - 0.05:  # gently up to the target
            v_new = target
            share = max(0.0, target - v) / max(1e-6, flat_out - v)
            want_throttle, want_brake = cruise + (1.0 - cruise) * share, 0.0
        else:  # braking
            v_new = max(target, v - A_BRAKE * DT)
            want_throttle = 0.0
            want_brake = min(1.0, (v - v_new) / (A_BRAKE * DT))
        throttle = _approach(throttle, want_throttle, 0.12)
        brake = _approach(brake, want_brake, 0.2)
        lon_acc = (v_new - v) / DT
        ds = (v + v_new) / 2 * DT
        v = v_new
        s += ds
        distance += ds
        t += DT
        lap_time += DT

        crossed = s >= n
        if crossed:
            s -= n
            lap += 1
            last_lap = lap_time
            best_lap = last_lap if best_lap == 0 else min(best_lap, last_lap)
            lap_time = 0.0
            fuel = max(0.0, fuel)
            pace_factor = 1.0 - rng.uniform(0.0, 0.015)
            if opts.laps and lap >= opts.laps:
                tail_left = opts.tail_s
        if tail_left is not None:
            tail_left -= DT
            if tail_left < 0:
                break

        # --- vehicle state ---------------------------------------------------
        i = int(s) % n
        k = track.curvature[i]
        lat_acc = v * v * k
        lat_norm = min(1.2, abs(lat_acc) / A_LAT)
        turning = abs(k) > 1e-6
        exiting = track.exit_zone[i] and want_throttle > 0.4 and lon_acc > 0.5

        rpm_now = _rpm(v, gear)
        if rpm_now > UPSHIFT_RPM and gear < len(GEAR_RATIOS):
            gear += 1
        elif gear > 1 and rpm_now < DOWNSHIFT_RPM and _rpm(v, gear - 1) < UPSHIFT_RPM - 300:
            gear -= 1
        rpm = max(IDLE_RPM, _rpm(v, gear))
        if v < 8.0 and throttle > 0.2:
            rpm = max(rpm, 3500.0)  # launch clutch slip
        rpm = min(MAX_RPM, rpm)

        noise = rng.gauss
        sa_front = lat_norm * 0.75 + noise(0, 0.02)
        sa_rear = lat_norm * 0.68 + noise(0, 0.02)
        sr_front = -0.28 * brake + noise(0, 0.005)
        sr_rear = 0.04 + 0.08 * throttle - 0.24 * brake + noise(0, 0.005)
        steer_gain = 1.0
        if issue == "understeer" and turning and not exiting:
            sa_front *= 1.6
            sa_rear *= 0.8
            steer_gain = 1.35
        elif issue == "oversteer-exit" and exiting:
            sa_rear = max(sa_rear * 1.9, 1.15 + rng.uniform(0, 0.4))
            steer_gain = -0.4  # counter-steer
        elif issue == "wheelspin" and gear <= 3 and throttle > 0.8 and (exiting or v < 20):
            sr_rear = 1.25 + rng.uniform(0, 0.6)
        elif issue == "lockup-rear" and brake > 0.6:
            sr_rear = -(1.25 + rng.uniform(0, 0.5))

        sign = track.turn_sign[i]
        slip_angle = Corners(sign * sa_front, sign * sa_front, sign * sa_rear, sign * sa_rear)
        slip_ratio = Corners(sr_front, sr_front, sr_rear, sr_rear)
        combined = Corners(*(math.hypot(a, r) for a, r in zip(slip_angle, slip_ratio, strict=True)))

        aero = 0.12 * (v / V_TOP) ** 2
        bump = 0.03 * math.sin(s / 7.0)
        dive = 0.18 * brake - 0.06 * throttle
        roll_load = 0.12 * lat_norm * sign  # right turn loads the left side
        front = 0.45 + aero + dive + bump
        rear = 0.45 + aero * 0.8 - dive * 0.5 + bump * 0.8
        if issue == "bottoming" and ((v > 60 and (s % 300) < 25) or brake > 0.8):
            front = 1.0
        susp = Corners(
            _clip(front + roll_load),
            _clip(front - roll_load),
            _clip(rear + roll_load),
            _clip(rear - roll_load),
        )

        speed_factor = v / 40.0 + 0.2
        load = (1 + 0.25 * lat_norm * sign, 1 - 0.25 * lat_norm * sign)
        for w in range(4):
            work = abs(slip_angle[w]) * 0.6 + abs(slip_ratio[w]) * 0.4 + 0.05
            work *= load[w % 2]
            temps[w] += (9.0 * work * speed_factor - 0.03 * (temps[w] - 85.0)) * DT
            wear[w] = max(0.0, wear[w] - 4.4e-6 * work * v * DT)
        fuel = max(0.0, fuel - 0.0004 * throttle * DT)

        power = throttle * PEAK_POWER_W * min(1.0, max(0.3, rpm / 7500.0))
        omega = rpm * 2 * math.pi / 60.0
        heading = track.heading[i]
        steer_cmd = max(-1.0, min(1.0, k * 2.7 / 0.12 * steer_gain))
        wheel_front = v / WHEEL_RADIUS

        yield Frame(
            recv_time=t,
            is_race_on=True,
            timestamp_ms=int(t * 1000) & 0xFFFFFFFF,
            engine_max_rpm=MAX_RPM,
            engine_idle_rpm=IDLE_RPM,
            current_engine_rpm=rpm,
            accel_x=lat_acc,
            accel_y=0.0,
            accel_z=lon_acc,
            vel_x=sign * sa_rear * 0.4,
            vel_y=0.0,
            vel_z=v,
            ang_vel_x=0.0,
            ang_vel_y=v * k,
            ang_vel_z=0.0,
            yaw=math.atan2(math.sin(heading), math.cos(heading)),
            pitch=-lon_acc * 0.002,
            roll=lat_acc * 0.003,
            susp_travel_norm=susp,
            tire_slip_ratio=slip_ratio,
            wheel_rot_speed=Corners(
                wheel_front,
                wheel_front,
                wheel_front * (1 + sr_rear),
                wheel_front * (1 + sr_rear),
            ),
            wheel_on_rumble=Corners(0, 0, 0, 0),
            wheel_in_puddle=Corners(0.0, 0.0, 0.0, 0.0),
            surface_rumble=Corners(0.0, 0.0, 0.0, 0.0),
            tire_slip_angle=slip_angle,
            tire_combined_slip=combined,
            susp_travel_m=Corners(*((x - 0.5) * 0.1 for x in susp)),
            car_ordinal=SIM_CAR_ORDINAL,
            car_class=SIM_CAR_CLASS,
            car_pi=SIM_CAR_PI,
            drivetrain=Drivetrain.RWD,
            num_cylinders=8,
            pos_x=track.x[i],
            pos_y=5.0 * math.sin(s / 400.0),
            pos_z=track.z[i],
            speed=v,
            power=power,
            torque=power / omega if omega > 1 else 0.0,
            tire_temp=Corners(*temps),
            boost=0.0,
            fuel=fuel,
            distance_traveled=distance,
            best_lap=best_lap,
            last_lap=last_lap,
            current_lap=lap_time,
            current_race_time=t,
            lap_number=lap,
            race_position=1,
            throttle=round(throttle * 255),
            brake=round(brake * 255),
            clutch=0,
            handbrake=0,
            gear=raw_gear(gear),
            steer=round(steer_cmd * 127),
            driving_line=0,
            ai_brake_diff=0,
            tire_wear=Corners(*wear),
            track_ordinal=SIM_TRACK_ORDINAL,
        )

    # Back in the menus: race-off packets.
    for _ in range(int(opts.menu_s * HZ)):
        t += DT
        yield blank_frame(
            recv_time=t, timestamp_ms=int(t * 1000) & 0xFFFFFFFF, gear=RAW_GEAR_NEUTRAL
        )


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))


def send(
    frames: Iterable[Frame],
    host: str,
    port: int,
    *,
    speedup: float = 1.0,
    fm7: bool = False,
) -> int:
    """Send frames as Car Dash packets, paced by their ``recv_time``."""
    return pace(((f.recv_time, encode(f, fm7=fm7)) for f in frames), host, port, speedup=speedup)
