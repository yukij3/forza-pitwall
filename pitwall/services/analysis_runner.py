"""Adapter between stored laps/sessions and the per-lap / per-session analysis.

Runs the engine on one worker thread (never on the event loop) and caches
results as JSON in the database, keyed by a fingerprint of everything the
result depends on, so a stale result is recomputed automatically.

v1 tracks no tunes, so the engine gets no tune values, tune changes or
previous session.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

from pitwall.services.engine import (
    ENGINE_MODULE,
    AnalysisFailed,
    LazyModule,
    to_dict,
    unit_system_for,
)
from pitwall.services.frames import LapFrames
from pitwall.storage.db import Store
from pitwall.telemetry.model import Frame

log = logging.getLogger(__name__)

T = TypeVar("T")
_OBJECT_CACHE_SIZE = 512


class AnalysisRunner:
    def __init__(
        self,
        store: Store,
        frames: LapFrames,
        engine: LazyModule | None = None,
    ) -> None:
        self.store = store
        self.frames = frames
        self.engine = engine or LazyModule(ENGINE_MODULE)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis")
        self._objects: OrderedDict[tuple[int, str], Any] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self.engine.available

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    async def _run(self, fn: Callable[..., T], *args: Any) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, fn, *args)

    # --- public async API ---------------------------------------------------

    async def lap(self, lap_id: int, frames: list[Frame] | None = None) -> dict[str, Any]:
        self.engine.require()
        return await self._run(self.lap_sync, lap_id, frames)

    async def session(self, session_id: int) -> dict[str, Any]:
        self.engine.require()
        return await self._run(self.session_sync, session_id)

    # --- sync implementation (worker thread) --------------------------------

    def lap_sync(self, lap_id: int, frames: list[Frame] | None = None) -> dict[str, Any]:
        lap = self.store.get_lap(lap_id)
        session = self.store.get_session(int(lap["session_id"]))
        unit_system = self._unit_system()
        fingerprint = self._lap_fingerprint(lap, unit_system)
        cached = self.store.get_cached_analysis("lap", lap_id, fingerprint)
        if cached is not None:
            return cached
        result = to_dict(self._lap_object(session, lap, unit_system, frames))
        self.store.put_cached_analysis("lap", lap_id, fingerprint, result)
        return result

    def session_sync(self, session_id: int) -> dict[str, Any]:
        session = self.store.get_session(session_id)
        laps = self.store.list_laps(session_id)
        unit_system = self._unit_system()
        fingerprint = _hash(
            self._engine_version(),
            unit_system,
            [(lap["id"], lap["kind"], lap["valid"], lap["lap_time"]) for lap in laps],
        )
        cached = self.store.get_cached_analysis("session", session_id, fingerprint)
        if cached is not None:
            return cached
        engine = self.engine.require()
        lap_objs = [self._lap_object(session, lap, unit_system) for lap in laps]
        ctx = engine.SessionContext(drivetrain=session.get("drivetrain"), unit_system=unit_system)
        result = to_dict(self._call(engine.analyze_session, lap_objs, ctx))
        self.store.put_cached_analysis("session", session_id, fingerprint, result)
        return result

    # --- helpers ------------------------------------------------------------

    def _engine_version(self) -> str:
        engine = self.engine.get()
        return str(getattr(engine, "__version__", "0")) if engine else "none"

    def _unit_system(self) -> str:
        return unit_system_for(self.store.get_settings())

    def _lap_fingerprint(self, lap: dict[str, Any], unit_system: str) -> str:
        return _hash(
            self._engine_version(), unit_system, lap["kind"], lap["valid"], lap["lap_time"]
        )

    def _lap_object(
        self,
        session: dict[str, Any],
        lap: dict[str, Any],
        unit_system: str,
        frames: list[Frame] | None = None,
    ) -> Any:
        """The engine's LapAnalysis object (kept in memory for session analysis)."""
        key = (int(lap["id"]), self._lap_fingerprint(lap, unit_system))
        with self._lock:
            if key in self._objects:
                self._objects.move_to_end(key)
                return self._objects[key]
        engine = self.engine.require()
        ctx = engine.LapContext(
            drivetrain=session.get("drivetrain"),  # "FWD" | "RWD" | "AWD" | None
            lap_kind=lap["kind"],
            lap_valid=lap["valid"],
            unit_system=unit_system,
            lap_time=lap["lap_time"],
        )
        lap_frames = frames if frames is not None else self.frames.get(lap)
        obj = self._call(engine.analyze_lap, lap_frames, ctx)
        with self._lock:
            self._objects[key] = obj
            while len(self._objects) > _OBJECT_CACHE_SIZE:
                self._objects.popitem(last=False)
        return obj

    @staticmethod
    def _call(fn: Callable[..., T], *args: Any) -> T:
        try:
            return fn(*args)
        except Exception as exc:
            log.exception("analysis engine failed")
            raise AnalysisFailed(f"{type(exc).__name__}: {exc}") from exc


def _hash(*parts: Any) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str).encode()
    return hashlib.sha1(raw).hexdigest()[:16]
