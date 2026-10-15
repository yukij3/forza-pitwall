"""Services container: everything the API needs, created once per app run."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Coroutine, Mapping
from typing import Any

from pitwall.api.convert import car_status, public_lap
from pitwall.api.live import LiveHub
from pitwall.config import Config
from pitwall.services.analysis_runner import AnalysisRunner
from pitwall.services.engine import unit_system_for
from pitwall.services.frames import LapFrames
from pitwall.services.live_analysis import LiveAnalysisService
from pitwall.services.recorder import Recorder
from pitwall.storage.db import NotFound, Store, iso
from pitwall.telemetry import canonical
from pitwall.telemetry.model import Frame
from pitwall.telemetry.receiver import TelemetryReceiver, start_udp

log = logging.getLogger(__name__)

HOUSEKEEPING_INTERVAL_S = 1.0


class Services:
    """Everything the API needs, created once per app run."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.store = Store(config.data_dir)
        if closed := self.store.close_dangling_sessions(iso()):
            log.warning("closed %d session(s) left open by a previous run", closed)
        self.active_tune_id: int | None = self.store.get_active_tune_id()
        self.frames = LapFrames(self.store)
        self.analysis = AnalysisRunner(self.store, self.frames)
        self.live_analysis = LiveAnalysisService(self.current_tune)
        self.hub = LiveHub(self.status, live_hz=config.live_hz, live_analysis=self.live_analysis)
        self.recorder = Recorder(self.store, on_lap=self._on_lap, on_change=self.hub.notify_status)
        self.recorder.set_auto_record(bool(self.store.get_settings()["auto_record"]))
        self.receiver = TelemetryReceiver(
            [self.recorder.handle_frame, self.live_analysis.on_frame, self.hub.on_frame]
        )
        self._tasks: set[asyncio.Task[Any]] = set()

    # --- lifecycle ----------------------------------------------------------

    async def start(self, *, udp: bool = True) -> None:
        if udp:
            await start_udp(self.receiver, self.config.bind, self.config.udp_port)
            log.info(
                "listening for Data Out on udp://%s:%d", self.config.bind, self.config.udp_port
            )
        self.live_analysis.start()
        self.spawn(self.hub.run())
        self.spawn(self._housekeeping())

    async def stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        try:
            self.recorder.close()
        finally:
            self.receiver.close()
            self.live_analysis.stop()
            self.analysis.close()
            self.store.close()

    def spawn(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _housekeeping(self) -> None:
        while True:
            await asyncio.sleep(HOUSEKEEPING_INTERVAL_S)
            try:
                self.recorder.tick()
            except Exception:
                log.exception("recorder housekeeping failed")

    # --- state shared by routes ---------------------------------------------

    def status(self) -> dict[str, Any]:
        stats = self.receiver.stats()
        frame: Frame | None = self.receiver.last_race_frame
        session = self.recorder.session
        age = stats.last_packet_age_s
        return {
            "receiver": {
                "listening": self.receiver.listening,
                "udp_port": self.config.udp_port,
                "public_host": self.config.public_host or None,
                "packets_per_sec": round(stats.packets_per_sec, 1),
                "last_packet_age_s": None if age is None else round(age, 3),
                "race_on": stats.race_on,
                "ignored_packets": stats.ignored_packets,
                "last_ignored_size": stats.last_ignored_size,
            },
            "recording": {
                "active": session is not None,
                "session_id": None if session is None else session["id"],
                "started_at": None if session is None else session["started_at"],
                "laps": self.recorder.lap_count if session is not None else 0,
            },
            "car": car_status(frame),
            "track_ordinal": None
            if frame is None
            else canonical.track_ordinal(frame.track_ordinal),
            "active_tune_id": self.active_tune_id,
        }

    def current_tune(self) -> tuple[Mapping[str, float], str]:
        """Values and unit system of the active tune (empty if none)."""
        if self.active_tune_id is not None:
            try:
                tune = self.store.get_tune(self.active_tune_id)
                return tune["values"], tune["unit_system"]
            except NotFound:
                pass
        return {}, unit_system_for(self.store.get_settings())

    def set_active_tune(self, tune_id: int | None) -> None:
        changed = tune_id != self.active_tune_id
        self.store.set_active_tune_id(tune_id)
        self.active_tune_id = tune_id
        if changed:
            self.live_analysis.on_tune_changed()
            self.hub.notify_status()

    # --- lap pipeline -------------------------------------------------------

    def _on_lap(self, session: dict[str, Any], lap: dict[str, Any], frames: list[Frame]) -> None:
        self.frames.put(int(lap["id"]), frames)
        self.hub.publish(
            {"type": "lap_completed", "session_id": session["id"], "lap": public_lap(lap)}
        )
        if self.analysis.available:
            self.spawn(self._analyze_lap(int(session["id"]), int(lap["id"])))

    async def _analyze_lap(self, session_id: int, lap_id: int) -> None:
        try:
            await self.analysis.lap(lap_id)
        except Exception:
            log.exception("analysis of lap %s failed", lap_id)
            return
        self.hub.publish({"type": "analysis_ready", "session_id": session_id, "lap_id": lap_id})
