"""Rulebook: symptom (finding id) -> ordered single-setting changes.

Each finding maps to candidate changes in order of preference. Candidates are
filtered by drivetrain (from ``pitwall.tune.settings`` plus rule-specific
limits), by the axle the symptom is on, and by the in-game range when the
current value is known. This table is shared by the per-lap analysis, the
session ranking and the live board.

Final Drive convention (Forza): a higher number is a shorter ratio (more
acceleration, lower speed per gear); a lower number is longer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pitwall.tune.settings import BY_KEY, Setting

from .results import Recommendation
from .thresholds import NO_AERO_PRIOR_FACTOR

MINUS = "−"
ARROW = "→"


@dataclass(frozen=True, slots=True)
class Change:
    setting: str
    direction: int  # +1 increase, -1 decrease
    prior: float  # how directly this setting addresses the symptom, 0..1
    why: str
    drivetrains: tuple[str, ...] | None = None  # extra limit beyond settings.py
    axles: tuple[str, ...] | None = None  # only when the finding is on these axles


def _c(setting: str, direction: int, prior: float, why: str, **kw: tuple[str, ...]) -> Change:
    return Change(setting, direction, prior, why, **kw)


_RWD_AWD = ("RWD", "AWD")

RULES: dict[str, tuple[Change, ...]] = {
    "entry-understeer": (
        _c(
            "diff.decel_rear",
            -1,
            1.0,
            "less deceleration lock lets the car rotate off-throttle",
            drivetrains=_RWD_AWD,
        ),
        _c(
            "diff.decel_front",
            -1,
            1.0,
            "less deceleration lock frees the front on turn-in",
            drivetrains=("FWD",),
        ),
        _c(
            "brake.balance",
            -1,
            0.8,
            "moving brake bias rearward helps the car rotate on the brakes",
        ),
        _c("arb.front", -1, 0.7, "a softer front bar gives the front more grip as load comes on"),
    ),
    "mid-understeer": (
        _c("arb.front", -1, 1.0, "a softer front anti-roll bar gives the front tires more grip"),
        _c("arb.rear", +1, 0.8, "a stiffer rear bar moves the balance toward the front"),
        _c("springs.front", -1, 0.7, "softer front springs add front mechanical grip"),
    ),
    "high-speed-understeer": (
        _c("aero.front", +1, 0.9, "more front downforce adds front grip where aero load is high"),
        _c("aero.rear", -1, 0.75, "less rear downforce moves the aero balance forward"),
        _c("arb.front", -1, 0.6, "a softer front bar adds front grip at any speed"),
    ),
    "exit-understeer": (
        _c(
            "diff.accel_front",
            -1,
            1.0,
            "less acceleration lock reduces power understeer",
            drivetrains=("FWD",),
        ),
        _c(
            "diff.center_balance",
            +1,
            1.0,
            "more drive to the rear reduces power understeer",
            drivetrains=("AWD",),
        ),
        _c("arb.front", -1, 0.8, "a softer front bar keeps the front biting as the car unwinds"),
        _c("arb.rear", +1, 0.7, "a stiffer rear bar helps the car rotate on exit"),
    ),
    "entry-oversteer": (
        _c(
            "diff.decel_rear",
            +1,
            1.0,
            "more deceleration lock keeps the rear in line off-throttle",
            drivetrains=_RWD_AWD,
        ),
        _c(
            "brake.balance", +1, 0.85, "more front brake bias takes braking load off the rear tires"
        ),
        _c("arb.rear", -1, 0.6, "a softer rear bar adds rear grip"),
    ),
    "mid-oversteer": (
        _c("arb.rear", -1, 1.0, "a softer rear anti-roll bar gives the rear tires more grip"),
        _c("arb.front", +1, 0.8, "a stiffer front bar moves the balance toward the rear"),
        _c("springs.rear", -1, 0.7, "softer rear springs add rear mechanical grip"),
    ),
    "high-speed-oversteer": (
        _c("aero.rear", +1, 0.9, "more rear downforce keeps the rear planted at speed"),
        _c("aero.front", -1, 0.75, "less front downforce moves the aero balance rearward"),
        _c("arb.rear", -1, 0.6, "a softer rear bar adds rear grip at any speed"),
    ),
    "exit-oversteer": (
        _c(
            "diff.accel_rear",
            -1,
            1.0,
            "less acceleration lock stops the rear stepping out on power",
            drivetrains=_RWD_AWD,
        ),
        _c("arb.rear", -1, 0.8, "a softer rear bar gives the rear more traction on exit"),
        _c(
            "diff.center_balance",
            -1,
            0.7,
            "less drive to the rear calms power oversteer",
            drivetrains=("AWD",),
        ),
        _c("springs.rear", -1, 0.6, "softer rear springs add rear traction"),
    ),
    "exit-wheelspin": (
        _c(
            "diff.accel_rear",
            -1,
            1.0,
            "less acceleration lock reduces wheelspin as power goes down",
            axles=("rear",),
        ),
        _c(
            "diff.accel_front",
            -1,
            1.0,
            "less acceleration lock reduces wheelspin as power goes down",
            axles=("front",),
        ),
        _c(
            "diff.center_balance",
            -1,
            0.8,
            "less drive to the spinning rear axle",
            drivetrains=("AWD",),
            axles=("rear",),
        ),
        _c(
            "diff.center_balance",
            +1,
            0.8,
            "less drive to the spinning front axle",
            drivetrains=("AWD",),
            axles=("front",),
        ),
        _c(
            "arb.rear",
            -1,
            0.6,
            "a softer rear bar keeps both rear tires loaded on exit",
            axles=("rear",),
        ),
        _c(
            "arb.front",
            -1,
            0.6,
            "a softer front bar keeps both front tires loaded on exit",
            axles=("front",),
        ),
    ),
    "lockup-front": (
        _c(
            "brake.balance", -1, 1.0, "moving brake bias rearward takes load off the locking fronts"
        ),
        _c("brake.pressure", -1, 0.8, "less brake pressure makes the fronts easier to modulate"),
    ),
    "lockup-rear": (
        _c("brake.balance", +1, 1.0, "moving brake bias forward takes load off the locking rears"),
        _c("brake.pressure", -1, 0.7, "less brake pressure makes the rears easier to modulate"),
    ),
    "lockup-both": (
        _c("brake.pressure", -1, 1.0, "both axles lock, so there is more brake torque than grip"),
    ),
    "braking-instability": (
        _c("brake.balance", +1, 1.0, "more front brake bias stops the rear sliding under braking"),
        _c(
            "diff.decel_rear",
            +1,
            0.8,
            "more deceleration lock stabilises the rear under braking",
            drivetrains=_RWD_AWD,
        ),
    ),
    "bottoming-front": (
        _c(
            "springs.ride_height_front",
            +1,
            1.0,
            "more ride height keeps the front off the bump stops",
        ),
        _c(
            "springs.front",
            +1,
            0.8,
            "stiffer front springs resist compression; use this if the ride height is already high",
        ),
        _c("damping.bump_front", +1, 0.6, "stiffer bump damping slows compression over bumps"),
    ),
    "bottoming-rear": (
        _c(
            "springs.ride_height_rear",
            +1,
            1.0,
            "more ride height keeps the rear off the bump stops",
        ),
        _c(
            "springs.rear",
            +1,
            0.8,
            "stiffer rear springs resist compression; use this if the ride height is already high",
        ),
        _c("damping.bump_rear", +1, 0.6, "stiffer bump damping slows compression over bumps"),
    ),
    "gearing-short": (
        _c(
            "gearing.final_drive",
            -1,
            1.0,
            "a lower final drive lengthens every gear, so the car "
            "stops hitting the limiter before the braking point",
        ),
    ),
    "gearing-long": (
        _c(
            "gearing.final_drive",
            +1,
            1.0,
            "a higher final drive shortens every gear, so the engine "
            "runs nearer its peak on the straight",
        ),
    ),
    "tires-hot-front": (
        _c(
            "tires.pressure_front",
            +1,
            1.0,
            "slightly more pressure reduces flex and heat; check hot pressures in game first",
        ),
    ),
    "tires-hot-rear": (
        _c(
            "tires.pressure_rear",
            +1,
            1.0,
            "slightly more pressure reduces flex and heat; check hot pressures in game first",
        ),
    ),
    "tires-cold-front": (
        _c(
            "tires.pressure_front",
            -1,
            1.0,
            "slightly less pressure lets the tires flex and build "
            "heat; check hot pressures in game first",
        ),
    ),
    "tires-cold-rear": (
        _c(
            "tires.pressure_rear",
            -1,
            1.0,
            "slightly less pressure lets the tires flex and build "
            "heat; check hot pressures in game first",
        ),
    ),
}

FINDING_TITLES: dict[str, str] = {
    "entry-understeer": "Understeer on corner entry",
    "mid-understeer": "Understeer mid-corner in slow corners",
    "high-speed-understeer": "Understeer in fast corners",
    "exit-understeer": "Understeer on corner exit",
    "entry-oversteer": "Oversteer on corner entry",
    "mid-oversteer": "Oversteer mid-corner in slow corners",
    "high-speed-oversteer": "Oversteer in fast corners",
    "exit-oversteer": "Oversteer on corner exit",
    "exit-wheelspin": "Wheelspin on corner exit",
    "lockup-front": "Front wheels lock under braking",
    "lockup-rear": "Rear wheels lock under braking",
    "lockup-both": "Front and rear wheels lock under braking",
    "braking-instability": "Rear unstable under braking",
    "bottoming-front": "Front suspension bottoms out",
    "bottoming-rear": "Rear suspension bottoms out",
    "gearing-short": "On the limiter at the end of the longest straight",
    "gearing-long": "Gearing too long for the longest straight",
    "tires-hot-front": "Front tires run hot",
    "tires-hot-rear": "Rear tires run hot",
    "tires-cold-front": "Front tires run cold",
    "tires-cold-rear": "Rear tires run cold",
}

# Short noun phrases for verdict texts ("mid-corner understeer down 40%").
FINDING_NAMES: dict[str, str] = {
    "entry-understeer": "entry understeer",
    "mid-understeer": "mid-corner understeer",
    "high-speed-understeer": "fast-corner understeer",
    "exit-understeer": "exit understeer",
    "entry-oversteer": "entry oversteer",
    "mid-oversteer": "mid-corner oversteer",
    "high-speed-oversteer": "fast-corner oversteer",
    "exit-oversteer": "exit oversteer",
    "exit-wheelspin": "exit wheelspin",
    "lockup-front": "front lockups",
    "lockup-rear": "rear lockups",
    "lockup-both": "lockups",
    "braking-instability": "instability under braking",
    "bottoming-front": "front bottoming",
    "bottoming-rear": "rear bottoming",
    "gearing-short": "time on the limiter",
    "gearing-long": "unused rpm on the straight",
    "tires-hot-front": "front tire heat",
    "tires-hot-rear": "rear tire heat",
    "tires-cold-front": "cold front tires",
    "tires-cold-rear": "cold rear tires",
}


# --- Steps, ranges, formatting -------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Step:
    imperial: float
    metric: float
    decimals_imperial: int
    decimals_metric: int

    def size(self, unit_system: str) -> float:
        return self.metric if unit_system == "metric" else self.imperial

    def decimals(self, unit_system: str) -> int:
        return self.decimals_metric if unit_system == "metric" else self.decimals_imperial


def _steps() -> dict[str, Step]:
    table: dict[str, Step] = {}
    for key in BY_KEY:
        group = key.split(".")[0]
        if key.startswith("tires.pressure"):
            table[key] = Step(0.5, 0.03, 1, 2)  # psi | bar
        elif key == "gearing.final_drive":
            table[key] = Step(0.10, 0.10, 2, 2)
        elif key.startswith("alignment.camber"):
            table[key] = Step(0.2, 0.2, 1, 1)
        elif key.startswith("alignment.toe"):
            table[key] = Step(0.1, 0.1, 1, 1)
        elif key == "alignment.caster":
            table[key] = Step(0.5, 0.5, 1, 1)
        elif group == "arb":
            table[key] = Step(2, 2, 0, 0)
        elif key.startswith("springs.ride_height"):
            table[key] = Step(0.2, 0.5, 1, 1)  # in | cm
        elif group == "springs":
            table[key] = Step(50, 1.0, 0, 1)  # lb/in | kgf/mm
        elif group == "damping":
            table[key] = Step(0.5, 0.5, 1, 1)
        elif key.startswith("geometry.roll_center"):
            table[key] = Step(0.2, 0.5, 1, 1)
        elif group == "geometry":
            table[key] = Step(5, 5, 0, 0)
        elif group == "aero":
            table[key] = Step(10, 5, 0, 0)  # lb | kgf
        elif key == "brake.balance":
            table[key] = Step(1, 1, 0, 0)
        elif key == "brake.pressure":
            table[key] = Step(5, 5, 0, 0)
        else:  # differential
            table[key] = Step(5, 5, 0, 0)
    return table


STEPS: dict[str, Step] = _steps()

# In-game limits where they are known; elsewhere only "not below zero".
RANGES: dict[str, tuple[float, float]] = {
    "arb.front": (1.0, 65.0),
    "arb.rear": (1.0, 65.0),
    "brake.balance": (0.0, 100.0),
    "diff.accel_front": (0.0, 100.0),
    "diff.decel_front": (0.0, 100.0),
    "diff.accel_rear": (0.0, 100.0),
    "diff.decel_rear": (0.0, 100.0),
    "diff.center_balance": (0.0, 100.0),
}
_NON_NEGATIVE_GROUPS = ("tires", "gearing", "springs", "damping", "aero", "brake")

_HINTS: dict[str, tuple[str, str]] = {  # (increase, decrease)
    "brake.balance": ("more front", "more rear"),
    "diff.center_balance": ("more rear", "more front"),
    "gearing.final_drive": ("shorter", "longer"),
}


def menu_path(setting: Setting) -> str:
    """ "Anti-roll Bars → Front", "Differential → Acceleration (Rear)", ..."""
    if setting.label == setting.section:
        return f"{setting.section} {ARROW} {setting.axle}" if setting.axle else setting.section
    head = f"{setting.section} {ARROW} {setting.label}"
    return f"{head} ({setting.axle})" if setting.axle else head


def display_unit(setting: Setting, unit_system: str) -> str:
    unit = setting.unit_metric if unit_system == "metric" else setting.unit_imperial
    return "%" if unit.startswith("%") else unit


def _unit_suffix(unit: str) -> str:
    if unit in ("", "%", "°"):
        return unit
    return f" {unit}"


def format_number(value: float, decimals: int) -> str:
    text = f"{abs(value):.{decimals}f}"
    return f"{MINUS}{text}" if value < 0 else text


def format_value(value: float | None) -> str:
    if value is None:
        return "?"
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text.replace("-", MINUS)


def format_step(setting: Setting, direction: int, step: float, unit_system: str) -> str:
    """ "+2", "−5%", "+0.2 in", "−0.10 (longer)"."""
    decimals = STEPS[setting.key].decimals(unit_system) if setting.key in STEPS else 2
    sign = "+" if direction > 0 else MINUS
    text = f"{sign}{abs(step):.{decimals}f}{_unit_suffix(display_unit(setting, unit_system))}"
    hint = _HINTS.get(setting.key)
    if hint:
        text += f" ({hint[0] if direction > 0 else hint[1]})"
    return text


def change_text(setting: Setting, direction: int, step: float, unit_system: str) -> str:
    return f"{menu_path(setting)}: {format_step(setting, direction, step, unit_system)}"


def clamp_value(key: str, value: float) -> float:
    lo, hi = RANGES.get(key, (None, None))
    if lo is None and key.split(".")[0] in _NON_NEGATIVE_GROUPS:
        lo = 0.0
    if lo is not None and value < lo:
        value = lo
    if hi is not None and value > hi:
        value = hi
    return value


def suggested_value(key: str, current: float | None, direction: int, step: float) -> float | None:
    if current is None:
        return None
    return round(clamp_value(key, current + direction * step), 3)


# --- Candidate selection ---------------------------------------------------------------
def _has_aero(tune_values: Mapping[str, float]) -> bool:
    return any(k.startswith("aero.") for k in tune_values)


def applicable_changes(
    finding_id: str,
    drivetrain: str,
    axle: str | None,
    tune_values: Mapping[str, float],
    unit_system: str = "imperial",
) -> list[tuple[Change, float]]:
    """Candidate changes that exist for this car, with their adjusted prior."""
    out: list[tuple[Change, float]] = []
    seen: set[str] = set()
    for ch in RULES.get(finding_id, ()):
        setting = BY_KEY.get(ch.setting)
        if setting is None or drivetrain not in setting.drivetrains:
            continue
        if ch.drivetrains is not None and drivetrain not in ch.drivetrains:
            continue
        if ch.axles is not None and axle not in ch.axles:
            continue
        if ch.setting in seen:
            continue
        current = tune_values.get(ch.setting)
        if current is not None:
            step = STEPS[ch.setting].size(unit_system)
            if suggested_value(ch.setting, current, ch.direction, step) == round(current, 3):
                continue  # already at the end of its range
        prior = ch.prior
        if ch.setting.startswith("aero.") and tune_values and not _has_aero(tune_values):
            prior *= NO_AERO_PRIOR_FACTOR
        seen.add(ch.setting)
        out.append((ch, prior))
    out.sort(key=lambda cp: -cp[1])
    return out


def build_recommendation(
    change: Change,
    *,
    finding_id: str,
    reason: str,
    confidence: float,
    unit_system: str,
    tune_values: Mapping[str, float],
    priority: int = 1,
    step: float | None = None,
    suggested: float | None = None,
    rec_id: str | None = None,
) -> Recommendation:
    setting = BY_KEY[change.setting]
    if step is None:
        step = STEPS[change.setting].size(unit_system)
    if suggested is None:
        suggested = suggested_value(
            change.setting, tune_values.get(change.setting), change.direction, step
        )
    slug = change.setting.replace(".", "-").replace("_", "-")
    return Recommendation(
        id=rec_id or f"{slug}-{'up' if change.direction > 0 else 'down'}",
        finding_id=finding_id,
        setting=change.setting,
        section=setting.section,
        label=setting.label,
        axle=setting.axle,
        direction="increase" if change.direction > 0 else "decrease",
        step=float(step),
        step_unit=display_unit(setting, unit_system),
        suggested_value=suggested,
        text=change_text(setting, change.direction, step, unit_system),
        reason=reason,
        confidence=max(0.0, min(1.0, confidence)),
        priority=priority,
    )


def describe_change(setting_key: str, from_value: float | None, to_value: float | None) -> str:
    """ "Anti-roll Bars → Front: 20 → 18" (falls back to the raw key)."""
    setting = BY_KEY.get(setting_key)
    name = menu_path(setting) if setting else setting_key
    if from_value is None and to_value is None:
        return f"{name}: changed"
    return f"{name}: {format_value(from_value)} {ARROW} {format_value(to_value)}"


def reason_text(evidence: str, why: str) -> str:
    evidence = evidence.rstrip(".")
    return f"{evidence}. {why[0].upper()}{why[1:]}."
