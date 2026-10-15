"""Result types of the baseline module. Every type has ``to_dict()`` (JSON-ready)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Source:
    title: str
    url: str
    used_for: str = ""  # which settings or facts the source backs

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "url": self.url, "used_for": self.used_for}


@dataclass(frozen=True, slots=True)
class Category:
    """A setup archetype: a group of in-game divisions that tune alike."""

    id: str
    name: str
    description: str
    divisions: tuple[str, ...]
    drivetrains: tuple[str, ...]  # drivetrains the cars come with; the first is the usual one

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "divisions": list(self.divisions),
            "drivetrains": list(self.drivetrains),
        }


@dataclass(frozen=True, slots=True)
class CarInfo:
    ordinal: int
    name: str
    division: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"ordinal": self.ordinal, "name": self.name, "division": self.division}


@dataclass(frozen=True, slots=True)
class Match:
    """Which category a car belongs to, and how sure we are.

    ``how``: ``ordinal`` (the car itself is pinned to a category),
    ``division`` (via the car's in-game division) or ``class_drivetrain``
    (guessed from class, drivetrain and PI). ``confidence``: high | medium | low.
    """

    category_id: str
    how: str
    confidence: str
    car: CarInfo | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "category_id": self.category_id,
            "how": self.how,
            "confidence": self.confidence,
            "car": self.car.to_dict() if self.car else None,
        }


@dataclass(frozen=True, slots=True)
class BaselineSetting:
    """One tuning-menu setting with its starting value.

    Absolute ``value`` and ``range`` only where the in-game scale is the same for
    every car; otherwise ``relative`` (slider position) and/or a rule in ``note``.
    ``basis``: ``published`` (an FM2023 source), ``carried_over`` (an FM7 /
    Forza Horizon source) or ``principles`` (general setup logic, no source).
    """

    key: str
    section: str
    label: str
    axle: str | None
    value: float | None
    range: tuple[float, float] | None
    unit: str
    relative: str | None
    note: str
    basis: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "section": self.section,
            "label": self.label,
            "axle": self.axle,
            "value": self.value,
            "range": list(self.range) if self.range else None,
            "unit": self.unit,
            "relative": self.relative,
            "note": self.note,
            "basis": self.basis,
        }


@dataclass(frozen=True, slots=True)
class Baseline:
    category: Category
    unit_system: str  # imperial | metric
    drivetrain: str  # the drivetrain the differential values are for
    settings: tuple[BaselineSetting, ...]
    notes: tuple[str, ...]
    sources: tuple[Source, ...]
    confidence: str  # low | medium (never high: these are starting points)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.to_dict(),
            "unit_system": self.unit_system,
            "drivetrain": self.drivetrain,
            "settings": [s.to_dict() for s in self.settings],
            "notes": list(self.notes),
            "sources": [s.to_dict() for s in self.sources],
            "confidence": self.confidence,
        }
