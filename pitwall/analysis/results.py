"""Contexts and result types of the analysis engine.

Every result has ``to_dict()`` returning JSON-ready data in canonical API units
(m/s, °C, m, s; pedals 0..1). Field names follow the API contract.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

DRIVETRAIN_NAMES = ("FWD", "RWD", "AWD")  # index = Frame.drivetrain value


def drivetrain_name(value: str | int | None, default: str = "RWD") -> str:
    """Accept "FWD"/"RWD"/"AWD" (any case) or the Data Out integer (0/1/2)."""
    if isinstance(value, str) and value.upper() in DRIVETRAIN_NAMES:
        return value.upper()
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 3:
        return DRIVETRAIN_NAMES[value]
    return default


def rnd(value: float | None, digits: int = 3) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _rnd_map(values: Mapping[str, float | None], digits: int = 3) -> dict[str, float | None]:
    return {k: rnd(v, digits) for k, v in values.items()}


# --- Contexts -------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TuneChange:
    """One setting changed between the previous session's tune and this one."""

    setting: str
    from_value: float | None
    to_value: float | None

    def to_dict(self) -> dict[str, Any]:
        return {"setting": self.setting, "from": self.from_value, "to": self.to_value}


@dataclass(frozen=True, slots=True)
class LapContext:
    drivetrain: str | int | None = None  # None: take it from the frames
    lap_kind: str = "flying"  # out | flying | in | partial
    lap_valid: bool = True
    tune_values: Mapping[str, float] = field(default_factory=dict)
    unit_system: str = "imperial"  # imperial | metric
    lap_time: float | None = None  # optional: the official lap time, if known


@dataclass(frozen=True, slots=True)
class SessionContext:
    drivetrain: str | int | None = None
    tune_values: Mapping[str, float] = field(default_factory=dict)
    unit_system: str = "imperial"
    previous_session: SessionAnalysis | None = None
    tune_changes: Sequence[TuneChange] = ()


# --- Building blocks -----------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Where:
    distance: float  # metres from the start of the lap
    corner: int | None  # 1-based corner number within the lap, None on a straight

    def to_dict(self) -> dict[str, Any]:
        return {"distance": rnd(self.distance, 1), "corner": self.corner}


@dataclass(frozen=True, slots=True)
class Finding:
    """A diagnosed symptom with its evidence."""

    id: str
    title: str
    severity: float  # 0..1
    confidence: float  # 0..1
    evidence: str
    where: tuple[Where, ...] = ()
    axle: str | None = None  # "front" | "rear" when the symptom is axle-specific
    item: str | None = None  # live board item that measures it
    laps: int = 1  # session: laps where it was seen
    consistency: float = 1.0  # session: share of valid laps where it was seen

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "severity": rnd(self.severity),
            "confidence": rnd(self.confidence),
            "evidence": self.evidence,
            "where": [w.to_dict() for w in self.where],
            "axle": self.axle,
            "item": self.item,
            "laps": self.laps,
            "consistency": rnd(self.consistency),
        }


@dataclass(frozen=True, slots=True)
class Recommendation:
    """Always exactly one setting, worded like the game's tuning menu."""

    id: str
    finding_id: str
    setting: str
    section: str
    label: str
    axle: str | None
    direction: str  # "increase" | "decrease"
    step: float
    step_unit: str
    suggested_value: float | None
    text: str
    reason: str
    confidence: float
    priority: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "finding_id": self.finding_id,
            "setting": self.setting,
            "section": self.section,
            "label": self.label,
            "axle": self.axle,
            "direction": self.direction,
            "step": self.step,
            "step_unit": self.step_unit,
            "suggested_value": self.suggested_value,
            "text": self.text,
            "reason": self.reason,
            "confidence": rnd(self.confidence),
            "priority": self.priority,
        }


@dataclass(frozen=True, slots=True)
class BoardItem:
    """One row of the tuning board (live, or for a single lap)."""

    id: str
    group: str
    title: str
    status: str  # ok | warn | bad | collecting
    value: float | None
    value_text: str
    target_text: str
    samples: int
    severity: float
    confidence: float
    recommendation: Recommendation | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "group": self.group,
            "title": self.title,
            "status": self.status,
            "value": rnd(self.value),
            "value_text": self.value_text,
            "target_text": self.target_text,
            "samples": self.samples,
            "severity": rnd(self.severity),
            "confidence": rnd(self.confidence),
            "recommendation": self.recommendation.to_dict() if self.recommendation else None,
        }


# --- Lap ---------------------------------------------------------------------------------
@dataclass(slots=True)
class LapMetrics:
    lap_time: float | None = None  # s
    distance: float = 0.0  # m
    max_speed: float = 0.0  # m/s
    avg_speed: float = 0.0  # m/s
    full_throttle_pct: float = 0.0  # share of lap time, 0..1
    braking_pct: float = 0.0
    corners: int = 0
    corners_slow: int = 0
    corners_fast: int = 0
    balance: dict[str, float | None] = field(default_factory=dict)  # entry/mid/exit
    balance_by_speed: dict[str, dict[str, float | None]] = field(default_factory=dict)
    wheelspin_events: int = 0
    lockups: dict[str, int] = field(default_factory=lambda: {"front": 0, "rear": 0})
    braking_zones: int = 0
    braking_instability_events: int = 0
    bottoming_events: int = 0
    bottoming: dict[str, int] = field(default_factory=lambda: {"front": 0, "rear": 0})
    limiter_time_s: float = 0.0
    top_gear_used: int = 0
    top_gear_max_rpm_pct: float = 0.0
    longest_straight_m: float = 0.0
    end_of_straight_rpm_pct: float | None = None
    end_of_straight_gear: int | None = None
    tire_temp_avg: dict[str, float] = field(default_factory=dict)  # °C
    tire_temp_max: dict[str, float] = field(default_factory=dict)  # °C
    tire_wear_delta: dict[str, float] = field(default_factory=dict)  # 0..1 per lap
    frames: int = 0
    sample_rate_hz: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "lap_time": rnd(self.lap_time),
            "distance": rnd(self.distance, 1),
            "max_speed": rnd(self.max_speed, 2),
            "avg_speed": rnd(self.avg_speed, 2),
            "full_throttle_pct": rnd(self.full_throttle_pct),
            "braking_pct": rnd(self.braking_pct),
            "corners": self.corners,
            "corners_slow": self.corners_slow,
            "corners_fast": self.corners_fast,
            "balance": _rnd_map(self.balance),
            "balance_by_speed": {k: _rnd_map(v) for k, v in self.balance_by_speed.items()},
            "wheelspin_events": self.wheelspin_events,
            "lockups": dict(self.lockups),
            "braking_zones": self.braking_zones,
            "braking_instability_events": self.braking_instability_events,
            "bottoming_events": self.bottoming_events,
            "bottoming": dict(self.bottoming),
            "limiter_time_s": rnd(self.limiter_time_s, 2),
            "top_gear_used": self.top_gear_used,
            "top_gear_max_rpm_pct": rnd(self.top_gear_max_rpm_pct),
            "longest_straight_m": rnd(self.longest_straight_m, 1),
            "end_of_straight_rpm_pct": rnd(self.end_of_straight_rpm_pct),
            "end_of_straight_gear": self.end_of_straight_gear,
            "tire_temp_avg": _rnd_map(self.tire_temp_avg, 1),
            "tire_temp_max": _rnd_map(self.tire_temp_max, 1),
            "tire_wear_delta": _rnd_map(self.tire_wear_delta, 4),
            "frames": self.frames,
            "sample_rate_hz": rnd(self.sample_rate_hz, 1),
        }


@dataclass(frozen=True, slots=True)
class CornerSummary:
    number: int
    start_distance: float
    apex_distance: float
    end_distance: float
    min_speed: float
    peak_lat_g: float
    speed_band: str  # "low" | "high"
    balance: dict[str, float | None]
    wheelspin: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "start_distance": rnd(self.start_distance, 1),
            "apex_distance": rnd(self.apex_distance, 1),
            "end_distance": rnd(self.end_distance, 1),
            "min_speed": rnd(self.min_speed, 2),
            "peak_lat_g": rnd(self.peak_lat_g, 2),
            "speed_band": self.speed_band,
            "balance": _rnd_map(self.balance),
            "wheelspin": self.wheelspin,
        }


@dataclass(frozen=True, slots=True)
class LapAnalysis:
    lap_number: int | None
    lap_kind: str
    valid: bool
    drivetrain: str
    lap_time: float | None
    metrics: LapMetrics
    corners: tuple[CornerSummary, ...] = ()
    findings: tuple[Finding, ...] = ()
    recommendations: tuple[Recommendation, ...] = ()
    items: tuple[BoardItem, ...] = ()
    limits: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "lap_number": self.lap_number,
            "lap_kind": self.lap_kind,
            "valid": self.valid,
            "drivetrain": self.drivetrain,
            "lap_time": rnd(self.lap_time),
            "metrics": self.metrics.to_dict(),
            "corners": [c.to_dict() for c in self.corners],
            "findings": [f.to_dict() for f in self.findings],
            "recommendations": [r.to_dict() for r in self.recommendations],
            "items": [i.to_dict() for i in self.items],
            "limits": list(self.limits),
        }


# --- Session -------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Verdict:
    changes: tuple[TuneChange, ...]
    result: str  # helped | hurt | mixed | no-clear-effect | no-change-recorded
    lap_time_delta: float | None  # s, median valid lap now minus before
    finding_deltas: dict[str, dict[str, float]]
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "changes": [c.to_dict() for c in self.changes],
            "result": self.result,
            "lap_time_delta": rnd(self.lap_time_delta),
            "finding_deltas": {k: _rnd_map(v) for k, v in self.finding_deltas.items()},
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class SessionAnalysis:
    laps_analyzed: int
    consistency: dict[str, Any]
    findings: tuple[Finding, ...] = ()
    next_change: Recommendation | None = None
    alternatives: tuple[Recommendation, ...] = ()
    verdict_on_last_change: Verdict | None = None
    limits: tuple[str, ...] = ()

    @property
    def lap_time_median(self) -> float | None:
        return self.consistency.get("median")

    @property
    def lap_time_stdev(self) -> float:
        return self.consistency.get("stdev") or 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "laps_analyzed": self.laps_analyzed,
            "consistency": dict(self.consistency),
            "findings": [f.to_dict() for f in self.findings],
            "next_change": self.next_change.to_dict() if self.next_change else None,
            "alternatives": [r.to_dict() for r in self.alternatives],
            "verdict_on_last_change": (
                self.verdict_on_last_change.to_dict() if self.verdict_on_last_change else None
            ),
            "limits": list(self.limits),
        }


# --- Live ---------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class LiveAnalysis:
    corners_seen: int
    window_corners: int
    window_laps: float | None
    focus: str | None
    items: tuple[BoardItem, ...]

    def item(self, item_id: str) -> BoardItem:
        for it in self.items:
            if it.id == item_id:
                return it
        raise KeyError(item_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "corners_seen": self.corners_seen,
            "window": {"corners": self.window_corners, "laps": rnd(self.window_laps, 2)},
            "focus": self.focus,
            "items": [i.to_dict() for i in self.items],
        }
