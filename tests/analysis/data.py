"""Cached synthetic data shared by the analysis tests (generation is the slow part)."""

from __future__ import annotations

from functools import cache

from pitwall.analysis import (
    LapAnalysis,
    LapContext,
    SessionAnalysis,
    SessionContext,
    analyze_lap,
    analyze_session,
)
from pitwall.analysis.synthetic import generate_laps
from pitwall.telemetry.model import Frame
from pitwall.tune.settings import BY_KEY

DRIVETRAIN_CODE = {"FWD": 0, "RWD": 1, "AWD": 2}
LAPS = 3
SEED = 11

# injected issue -> (finding id, board item)
EXPECTED: dict[str, tuple[str, str]] = {
    "understeer": ("mid-understeer", "mid_balance_low"),
    "high-speed-understeer": ("high-speed-understeer", "mid_balance_high"),
    "oversteer-entry": ("entry-oversteer", "entry_balance"),
    "oversteer-exit": ("exit-oversteer", "exit_balance"),
    "unstable-braking": ("braking-instability", "braking_stability"),
    "wheelspin": ("exit-wheelspin", "exit_wheelspin"),
    "lockup-front": ("lockup-front", "lockups_front"),
    "lockup-rear": ("lockup-rear", "lockups_rear"),
    "bottoming": ("bottoming-front", "bottoming_front"),
    "bottoming-rear": ("bottoming-rear", "bottoming_rear"),
    "gearing-short": ("gearing-short", "gearing"),
    "gearing-long": ("gearing-long", "gearing"),
}

# (issue, drivetrain) -> (setting, direction) of the expected next change
EXPECTED_CHANGE: dict[tuple[str, str], tuple[str, str]] = {}
for _dt in ("FWD", "RWD", "AWD"):
    EXPECTED_CHANGE.update(
        {
            ("understeer", _dt): ("arb.front", "decrease"),
            ("high-speed-understeer", _dt): ("aero.front", "increase"),
            ("oversteer-entry", _dt): (
                ("brake.balance", "increase") if _dt == "FWD" else ("diff.decel_rear", "increase")
            ),
            ("oversteer-exit", _dt): (
                ("arb.rear", "decrease") if _dt == "FWD" else ("diff.accel_rear", "decrease")
            ),
            ("unstable-braking", _dt): ("brake.balance", "increase"),
            ("wheelspin", _dt): (
                ("diff.accel_front", "decrease")
                if _dt == "FWD"
                else ("diff.accel_rear", "decrease")
            ),
            ("lockup-front", _dt): ("brake.balance", "decrease"),
            ("lockup-rear", _dt): ("brake.balance", "increase"),
            ("bottoming", _dt): ("springs.ride_height_front", "increase"),
            ("bottoming-rear", _dt): ("springs.ride_height_rear", "increase"),
            ("gearing-short", _dt): ("gearing.final_drive", "decrease"),
            ("gearing-long", _dt): ("gearing.final_drive", "increase"),
        }
    )


@cache
def laps(issue: str, drivetrain: str = "RWD", seed: int = SEED) -> tuple[tuple[Frame, ...], ...]:
    """Three consecutive flying laps of one continuous stint."""
    return tuple(tuple(lap) for lap in generate_laps(issue, LAPS, drivetrain=drivetrain, seed=seed))


@cache
def lap_analyses(issue: str, drivetrain: str = "RWD") -> tuple[LapAnalysis, ...]:
    ctx = LapContext(drivetrain=DRIVETRAIN_CODE[drivetrain])
    return tuple(analyze_lap(lap, ctx) for lap in laps(issue, drivetrain))


@cache
def session(issue: str, drivetrain: str = "RWD") -> SessionAnalysis:
    ctx = SessionContext(drivetrain=DRIVETRAIN_CODE[drivetrain])
    return analyze_session(lap_analyses(issue, drivetrain), ctx)


def exists_for(setting: str, drivetrain: str) -> bool:
    return drivetrain in BY_KEY[setting].drivetrains
