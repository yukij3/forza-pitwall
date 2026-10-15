"""Lazy access to the analysis engine (``pitwall.analysis``).

The engine is optional at runtime: if it can't be imported, analysis endpoints
answer 503 ``analysis_unavailable`` and the rest of the app keeps working.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable, Mapping
from types import ModuleType
from typing import Any

from pitwall.telemetry.model import Drivetrain

log = logging.getLogger(__name__)

ENGINE_MODULE = "pitwall.analysis"
LIVE_MODULE = "pitwall.analysis.live"

DRIVETRAIN_CODES = {"FWD": Drivetrain.FWD, "RWD": Drivetrain.RWD, "AWD": Drivetrain.AWD}


class AnalysisUnavailable(RuntimeError):
    pass


class AnalysisFailed(RuntimeError):
    pass


class LazyModule:
    """Imports a module on first use and remembers the outcome."""

    def __init__(self, name: str, loader: Callable[[str], ModuleType] | None = None) -> None:
        self.name = name
        self._loader = loader or importlib.import_module
        self._module: ModuleType | None = None
        self._tried = False

    def get(self) -> ModuleType | None:
        if not self._tried:
            self._tried = True
            try:
                self._module = self._loader(self.name)
            except ImportError as exc:
                log.info("%s not available: %s", self.name, exc)
            except Exception:
                log.exception("%s failed to import", self.name)
        return self._module

    def require(self) -> ModuleType:
        module = self.get()
        if module is None:
            raise AnalysisUnavailable(f"{self.name} is not installed")
        return module

    @property
    def available(self) -> bool:
        return self.get() is not None


def drivetrain_code(name: str | None) -> int:
    return DRIVETRAIN_CODES.get(name or "", Drivetrain.RWD)


def unit_system_for(settings: Mapping[str, Any]) -> str:
    """Fallback unit system when no tune is known: follow the speed unit setting."""
    return "imperial" if settings.get("units", {}).get("speed") == "mph" else "metric"


def to_dict(result: Any) -> Any:
    return result.to_dict() if hasattr(result, "to_dict") else result
