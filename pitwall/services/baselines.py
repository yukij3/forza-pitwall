"""Adapter for baseline setups (``pitwall.baselines``, optional at runtime)."""

from __future__ import annotations

from typing import Any

from pitwall.services.engine import BASELINES_MODULE, BaselinesUnavailable, LazyModule, to_dict
from pitwall.telemetry.model import Frame


class UnknownCategory(LookupError):
    pass


class BaselineService:
    def __init__(self, module: LazyModule | None = None) -> None:
        self.module = module or LazyModule(BASELINES_MODULE, error=BaselinesUnavailable)
        self._car_info: dict[int, dict[str, Any] | None] = {}

    @property
    def available(self) -> bool:
        return self.module.available

    def categories(self) -> list[Any]:
        return [to_dict(c) for c in self.module.require().categories()]

    def baseline(
        self, category_id: str, unit_system: str, drivetrain: int | None = None
    ) -> dict[str, Any]:
        """Baseline for a category; ``drivetrain`` picks the differential settings."""
        module = self.module.require()
        kwargs = {} if drivetrain is None else {"drivetrain": drivetrain}
        try:
            result = module.baseline(category_id, unit_system, **kwargs)
        except (LookupError, ValueError) as exc:
            raise UnknownCategory(f"baseline category {category_id!r}") from exc
        if result is None:
            raise UnknownCategory(f"baseline category {category_id!r}")
        return to_dict(result)

    def for_car(self, frame: Frame | None, unit_system: str) -> dict[str, Any]:
        """Best match for the car on track and its baseline (both None if unknown)."""
        module = self.module.require()
        if frame is None or frame.car_ordinal == 0:
            return {"match": None, "baseline": None}
        match = module.match(frame.car_ordinal, frame.car_pi, frame.car_class, frame.drivetrain)
        if match is None:
            return {"match": None, "baseline": None}
        match_dict = to_dict(match)
        category_id = match_dict["category_id"]
        baseline = self.baseline(category_id, unit_system, frame.drivetrain)
        return {"match": match_dict, "baseline": baseline}

    def car_info(self, ordinal: int) -> dict[str, Any] | None:
        """Name/division of a car if the baselines module knows it (cached)."""
        if ordinal in self._car_info:
            return self._car_info[ordinal]
        module = self.module.get()
        info = None
        if module is not None:
            try:
                found = module.car_info(ordinal)
            except Exception:
                found = None
            info = to_dict(found) if found is not None else None
        self._car_info[ordinal] = info
        return info
