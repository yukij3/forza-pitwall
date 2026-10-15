"""Shared telemetry data model.

This module is the contract between the packet layer (``pitwall.telemetry``),
the analysis engine (``pitwall.analysis``) and the API. Field names mirror the
official Forza Motorsport (2023) "Car Dash" Data Out format, in snake_case.

Values are kept in the game's raw units here (see comments). Conversion to the
API's canonical units happens at the API boundary, not in this model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


class Corners(NamedTuple):
    """One value per wheel: front-left, front-right, rear-left, rear-right."""

    fl: float
    fr: float
    rl: float
    rr: float

    @property
    def front(self) -> float:
        return (self.fl + self.fr) / 2

    @property
    def rear(self) -> float:
        return (self.rl + self.rr) / 2


class Drivetrain:
    FWD = 0
    RWD = 1
    AWD = 2


@dataclass(slots=True, frozen=True)
class Frame:
    """One Data Out packet (60 per second while the game is sending)."""

    # --- receive metadata (not part of the packet) ---
    recv_time: float  # host clock, seconds (time.monotonic() at receive)

    # --- "Sled" section ---
    is_race_on: bool  # False in menus / paused
    timestamp_ms: int  # game clock, wraps around
    engine_max_rpm: float
    engine_idle_rpm: float
    current_engine_rpm: float

    # Car-local space: x = right, y = up, z = forward.
    accel_x: float  # m/s^2
    accel_y: float
    accel_z: float
    vel_x: float  # m/s
    vel_y: float
    vel_z: float
    ang_vel_x: float  # rad/s (pitch rate)
    ang_vel_y: float  # rad/s (yaw rate)
    ang_vel_z: float  # rad/s (roll rate)
    yaw: float  # rad
    pitch: float
    roll: float

    susp_travel_norm: Corners  # 0.0 = max stretch, 1.0 = max compression
    tire_slip_ratio: Corners  # normalized: 0 = full grip, |x| > 1.0 = grip lost
    wheel_rot_speed: Corners  # rad/s
    wheel_on_rumble: Corners  # 1 if on rumble strip
    wheel_in_puddle: Corners  # 0..1
    surface_rumble: Corners  # force-feedback rumble
    tire_slip_angle: Corners  # normalized: 0 = full grip, |x| > 1.0 = grip lost
    tire_combined_slip: Corners  # normalized: 0 = full grip, |x| > 1.0 = grip lost
    susp_travel_m: Corners  # meters

    car_ordinal: int  # unique car model id
    car_class: int  # class index (verify mapping against official docs)
    car_pi: int  # performance index
    drivetrain: int  # see Drivetrain
    num_cylinders: int

    # --- "Dash" section ---
    pos_x: float  # world space, meters
    pos_y: float
    pos_z: float
    speed: float  # m/s
    power: float  # watts
    torque: float  # newton-meters
    tire_temp: Corners  # degrees Fahrenheit
    boost: float
    fuel: float  # 0..1
    distance_traveled: float  # meters
    best_lap: float  # seconds
    last_lap: float  # seconds
    current_lap: float  # seconds
    current_race_time: float  # seconds
    lap_number: int  # increments when crossing the line
    race_position: int
    throttle: int  # 0..255
    brake: int  # 0..255
    clutch: int  # 0..255
    handbrake: int  # 0..255
    gear: int  # see official docs for reverse/neutral encoding
    steer: int  # -127..127
    driving_line: int  # -127..127
    ai_brake_diff: int  # -127..127

    # --- Forza Motorsport (2023) additions ---
    tire_wear: Corners  # 0..1
    track_ordinal: int  # unique track layout id
