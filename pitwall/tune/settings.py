"""Canonical tune settings, in Forza Motorsport (2023) tuning-menu order.

Every recommendation, stored tune and UI table refers to settings by ``key``.
``section`` and ``label`` are the exact English names shown in the game menu so
a recommendation can be read out as "Anti-roll Bars -> Front: -2".

Values are stored as the number the player sees in the game, in the unit the
game displays (``imperial`` or ``metric`` per tune). ``unit`` below lists both.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Setting:
    key: str
    section: str  # in-game tuning section
    label: str  # in-game setting name
    axle: str | None  # "Front", "Rear" or None
    unit_imperial: str
    unit_metric: str
    drivetrains: tuple[str, ...] = ("FWD", "RWD", "AWD")


SETTINGS: tuple[Setting, ...] = (
    # Tires
    Setting("tires.pressure_front", "Tires", "Tire Pressure", "Front", "psi", "bar"),
    Setting("tires.pressure_rear", "Tires", "Tire Pressure", "Rear", "psi", "bar"),
    # Gearing
    Setting("gearing.final_drive", "Gearing", "Final Drive", None, "", ""),
    # Alignment
    Setting("alignment.camber_front", "Alignment", "Camber", "Front", "°", "°"),
    Setting("alignment.camber_rear", "Alignment", "Camber", "Rear", "°", "°"),
    Setting("alignment.toe_front", "Alignment", "Toe", "Front", "°", "°"),
    Setting("alignment.toe_rear", "Alignment", "Toe", "Rear", "°", "°"),
    Setting("alignment.caster", "Alignment", "Caster", "Front", "°", "°"),
    # Anti-roll Bars
    Setting("arb.front", "Anti-roll Bars", "Anti-roll Bars", "Front", "", ""),
    Setting("arb.rear", "Anti-roll Bars", "Anti-roll Bars", "Rear", "", ""),
    # Springs
    Setting("springs.front", "Springs", "Springs", "Front", "lb/in", "kgf/mm"),
    Setting("springs.rear", "Springs", "Springs", "Rear", "lb/in", "kgf/mm"),
    Setting("springs.ride_height_front", "Springs", "Ride Height", "Front", "in", "cm"),
    Setting("springs.ride_height_rear", "Springs", "Ride Height", "Rear", "in", "cm"),
    # Damping
    Setting("damping.rebound_front", "Damping", "Rebound Stiffness", "Front", "", ""),
    Setting("damping.rebound_rear", "Damping", "Rebound Stiffness", "Rear", "", ""),
    Setting("damping.bump_front", "Damping", "Bump Stiffness", "Front", "", ""),
    Setting("damping.bump_rear", "Damping", "Bump Stiffness", "Rear", "", ""),
    # Suspension geometry (Forza Motorsport 2023)
    Setting("geometry.roll_center_front", "Geometry", "Roll Center Height Offset", "Front", "in", "cm"),
    Setting("geometry.roll_center_rear", "Geometry", "Roll Center Height Offset", "Rear", "in", "cm"),
    Setting("geometry.anti_front", "Geometry", "Anti-dive", "Front", "%", "%"),
    Setting("geometry.anti_rear", "Geometry", "Anti-squat", "Rear", "%", "%"),
    # Aero
    Setting("aero.front", "Aero", "Downforce", "Front", "lb", "kgf"),
    Setting("aero.rear", "Aero", "Downforce", "Rear", "lb", "kgf"),
    # Brake
    Setting("brake.balance", "Brake", "Braking Balance", None, "% front", "% front"),
    Setting("brake.pressure", "Brake", "Braking Pressure", None, "%", "%"),
    # Differential
    Setting("diff.accel_front", "Differential", "Acceleration", "Front", "%", "%", ("FWD", "AWD")),
    Setting("diff.decel_front", "Differential", "Deceleration", "Front", "%", "%", ("FWD", "AWD")),
    Setting("diff.accel_rear", "Differential", "Acceleration", "Rear", "%", "%", ("RWD", "AWD")),
    Setting("diff.decel_rear", "Differential", "Deceleration", "Rear", "%", "%", ("RWD", "AWD")),
    Setting("diff.center_balance", "Differential", "Center Balance", None, "% rear", "% rear", ("AWD",)),
)

BY_KEY: dict[str, Setting] = {s.key: s for s in SETTINGS}
