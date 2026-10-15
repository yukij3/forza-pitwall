"""Recorder: turns the live frame stream into sessions, laps and raw packet files."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from pitwall.storage.db import Store, iso
from pitwall.storage.rawlog import RawWriter
from pitwall.telemetry import canonical
from pitwall.telemetry.laps import LapSegment, LapSegmenter
from pitwall.telemetry.model import Frame

log = logging.getLogger(__name__)

AUTO_STOP_S = 30.0  # auto-recorded sessions stop after this long without race-on frames
FLUSH_INTERVAL_S = 1.0
AUTO_NOTE = "Auto-recorded"

LapCallback = Callable[[dict[str, Any], dict[str, Any], list[Frame]], None]


class RecordingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class Recorder:
    def __init__(
        self,
        store: Store,
        *,
        on_lap: LapCallback | None = None,
        on_change: Callable[[], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.on_lap = on_lap
        self.on_change = on_change
        self.clock = clock
        self.wall_clock = wall_clock
        self.auto_record = False
        self.session: dict[str, Any] | None = None
        self.lap_count = 0
        self._auto_session = False
        self._writer: RawWriter | None = None
        self._segmenter: LapSegmenter | None = None
        self._car_known = False
        self._last_race_on = False
        self._last_race_on_time = 0.0
        self._last_flush = 0.0

    @property
    def active(self) -> bool:
        return self.session is not None

    @property
    def session_id(self) -> int | None:
        return None if self.session is None else int(self.session["id"])

    def set_auto_record(self, enabled: bool) -> None:
        if enabled and not self.auto_record:
            # Let the next race-on frame start a session even if the race is already on.
            self._last_race_on = False
        self.auto_record = enabled

    # --- control ------------------------------------------------------------

    def start(self, note: str = "", *, auto: bool = False) -> dict[str, Any]:
        if self.session is not None:
            raise RecordingError("already_recording", "A recording is already running")
        session = self.store.create_session(
            started_at=iso(self.wall_clock()),
            tune_id=self.store.get_active_tune_id(),
            note=note,
        )
        raw_path = self.store.raw_path(session)
        assert raw_path is not None
        self._writer = RawWriter(raw_path)
        self._segmenter = LapSegmenter(wall_clock=self.wall_clock)
        self.session = session
        self.lap_count = 0
        self._auto_session = auto
        self._car_known = False
        self._last_race_on_time = self.clock()
        self._last_flush = self._last_race_on_time
        log.info("recording started: session %s", session["id"])
        self._changed()
        return session

    def stop(self) -> dict[str, Any]:
        if self.session is None or self._writer is None or self._segmenter is None:
            raise RecordingError("not_recording", "No recording is running")
        session_id = int(self.session["id"])
        try:
            self._store_laps(self._segmenter.finish())
        finally:
            self._writer.close()
            self.store.stop_session(
                session_id, stopped_at=iso(self.wall_clock()), frame_count=self._writer.count
            )
            self.session = None
            self._writer = None
            self._segmenter = None
            self._auto_session = False
        log.info("recording stopped: session %s", session_id)
        self._changed()
        return self.store.get_session(session_id)

    def close(self) -> None:
        """Shutdown: stop an active recording so its files are complete."""
        if self.session is not None:
            self.stop()

    # --- frame stream -------------------------------------------------------

    def handle_frame(self, frame: Frame, raw: bytes) -> None:
        if (
            self.auto_record
            and self.session is None
            and frame.is_race_on
            and not self._last_race_on
        ):
            self.start(AUTO_NOTE, auto=True)
        self._last_race_on = frame.is_race_on
        if self.session is None or self._writer is None or self._segmenter is None:
            return

        if not frame.is_race_on:
            self._segmenter.note_race_off()
            if self._auto_session and frame.recv_time - self._last_race_on_time >= AUTO_STOP_S:
                self.stop()
            return

        self._last_race_on_time = frame.recv_time
        index = self._writer.append(frame.recv_time, raw)
        if not self._car_known:
            self._set_car(frame)
        finished = self._segmenter.add(frame, index)
        if finished:
            self._store_laps(finished)
        elif frame.recv_time - self._last_flush >= FLUSH_INTERVAL_S:
            self._writer.flush()
            self._last_flush = frame.recv_time

    def tick(self, now: float | None = None) -> None:
        """Housekeeping, called about once per second."""
        if self.session is None or self._writer is None:
            return
        now = self.clock() if now is None else now
        if self._auto_session and now - self._last_race_on_time >= AUTO_STOP_S:
            self.stop()
            return
        self._writer.flush()

    # --- internals ----------------------------------------------------------

    def _set_car(self, frame: Frame) -> None:
        assert self.session is not None
        self.store.set_session_car(
            int(self.session["id"]),
            car_ordinal=frame.car_ordinal,
            car_pi=frame.car_pi,
            car_class=frame.car_class,
            drivetrain=canonical.drivetrain_name(frame.drivetrain),
            track_ordinal=canonical.track_ordinal(frame.track_ordinal),
        )
        self.session = self.store.get_session(int(self.session["id"]))
        self._car_known = True
        self._changed()

    def _store_laps(self, segments: list[LapSegment]) -> None:
        if not segments or self.session is None or self._writer is None:
            return
        self._writer.flush()
        for seg in segments:
            lap = self.store.insert_lap(
                session_id=int(self.session["id"]),
                number=seg.number,
                lap_time=None if seg.lap_time is None else round(seg.lap_time, 3),
                kind=seg.kind,
                valid=seg.valid,
                invalid_reason=seg.invalid_reason,
                frame_count=seg.frame_count,
                first_frame=seg.first_index,
                started_at=iso(seg.started_wall),
            )
            self.lap_count += 1
            if self.on_lap is not None:
                try:
                    self.on_lap(self.session, lap, seg.frames)
                except Exception:
                    log.exception("lap callback failed")
        self._changed()

    def _changed(self) -> None:
        if self.on_change is not None:
            self.on_change()
