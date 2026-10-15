"""Imperial <-> metric conversion for tuning-menu units.

Baseline data is stored in the game's imperial units (psi, lb/in, in, lb).
Unitless sliders, degrees and percentages are the same in both systems.
"""

from __future__ import annotations

PSI_PER_BAR = 14.5037738
KGF_MM_PER_LB_IN = 0.45359237 / 25.4  # 1 lb/in = 0.017858 kgf/mm
CM_PER_IN = 2.54
KGF_PER_LB = 0.45359237

# imperial unit -> (metric unit, factor, decimals shown in metric)
_TO_METRIC: dict[str, tuple[str, float, int]] = {
    "psi": ("bar", 1.0 / PSI_PER_BAR, 2),
    "lb/in": ("kgf/mm", KGF_MM_PER_LB_IN, 2),
    "in": ("cm", CM_PER_IN, 1),
    "lb": ("kgf", KGF_PER_LB, 0),
}
# imperial unit -> decimals shown in imperial
_IMPERIAL_DECIMALS = {"psi": 1, "lb/in": 0, "in": 1, "lb": 0}

UNIT_SYSTEMS = ("imperial", "metric")


def to_metric(value: float, unit: str) -> float:
    """Convert a value in an imperial tuning unit to the matching metric unit."""
    if unit not in _TO_METRIC:
        return value
    _, factor, decimals = _TO_METRIC[unit]
    return round(value * factor, decimals)


def to_imperial(value: float, metric_unit: str) -> float:
    """Convert a value in a metric tuning unit back to imperial."""
    for imperial, (metric, factor, _) in _TO_METRIC.items():
        if metric == metric_unit:
            return round(value / factor, _IMPERIAL_DECIMALS[imperial])
    return value


def convert(value: float, imperial_unit: str, unit_system: str) -> float:
    """``value`` (stored in ``imperial_unit``) as shown in ``unit_system``."""
    if unit_system == "metric":
        return to_metric(value, imperial_unit)
    return round(value, _IMPERIAL_DECIMALS.get(imperial_unit, 2))


def check_unit_system(unit_system: str) -> str:
    if unit_system not in UNIT_SYSTEMS:
        raise ValueError(f"unit_system must be 'imperial' or 'metric', not {unit_system!r}")
    return unit_system
