"""Lazy access to optional modules (``pitwall.analysis``, ``pitwall.baselines``).

If such a module can't be imported, the endpoints that need it answer 503 and
the rest of the app keeps working.
"""

from __future__ import annotations

import dataclasses
import importlib
import logging
from collections.abc import Callable, Mapping
from types import ModuleType
from typing import Any

log = logging.getLogger(__name__)

ENGINE_MODULE = "pitwall.analysis"
LIVE_MODULE = "pitwall.analysis.live"
BASELINES_MODULE = "pitwall.baselines"


class ModuleUnavailable(RuntimeError):
    pass


class AnalysisUnavailable(ModuleUnavailable):
    pass


class BaselinesUnavailable(ModuleUnavailable):
    pass


class AnalysisFailed(RuntimeError):
    pass


class LazyModule:
    """Imports a module on first use and remembers the outcome."""

    def __init__(
        self,
        name: str,
        loader: Callable[[str], ModuleType] | None = None,
        *,
        error: type[ModuleUnavailable] = AnalysisUnavailable,
    ) -> None:
        self.name = name
        self.error = error
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
            raise self.error(f"{self.name} is not installed")
        return module

    @property
    def available(self) -> bool:
        return self.get() is not None


def unit_system_for(settings: Mapping[str, Any]) -> str:
    """Unit system implied by the settings: follows the speed unit."""
    return "imperial" if settings.get("units", {}).get("speed") == "mph" else "metric"


def to_dict(result: Any) -> Any:
    """JSON-ready form of a result object (``to_dict()``, dataclass, or as is)."""
    if hasattr(result, "to_dict"):
        return result.to_dict()
    if dataclasses.is_dataclass(result) and not isinstance(result, type):
        return dataclasses.asdict(result)
    return result
