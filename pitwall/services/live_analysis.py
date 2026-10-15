"""Live tuning board: feeds race-on frames to the engine's ``LiveAnalyzer``.

* Frames are handed to a worker thread through a bounded queue, so a slow
  ``push()`` never blocks the UDP/event loop; when the queue is full, new frames
  are dropped and counted.
* The analyzer is rebuilt (with the current drivetrain) when the car or track
  changes and on manual reset (the player presses it after changing the setup
  in game). Frames queued before a reset are discarded.
* Snapshots are published at most every ``min_interval_s`` and only when they
  changed; the broadcaster calls :meth:`poll` from its own loop.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

from pitwall.services.engine import LIVE_MODULE, AnalysisUnavailable, LazyModule, to_dict
from pitwall.telemetry.model import Drivetrain, Frame

log = logging.getLogger(__name__)

UnitSystemProvider = Callable[[], str]

QUEUE_SIZE = 240  # 4 s of frames at 60 Hz
MIN_INTERVAL_S = 0.5  # at most 2 updates per second
_STOP = object()


class LiveAnalysisService:
    def __init__(
        self,
        unit_system: UnitSystemProvider,
        *,
        module: LazyModule | None = None,
        queue_size: int = QUEUE_SIZE,
        min_interval_s: float = MIN_INTERVAL_S,
    ) -> None:
        self.module = module or LazyModule(LIVE_MODULE)
        self.unit_system = unit_system
        self.min_interval_s = min_interval_s
        self.dropped_frames = 0
        self.resets = 0
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=queue_size)
        self._lock = threading.Lock()
        self._analyzer: Any = None
        self._generation = 0
        self._car_key: tuple[int, int] | None = None
        self._drivetrain = Drivetrain.RWD
        self._latest: dict[str, Any] | None = None
        self._dirty = False
        self._last_sent_at: float | None = None
        self._last_sent: dict[str, Any] | None = None
        self._thread: threading.Thread | None = None

    @property
    def available(self) -> bool:
        return self.module.available

    # --- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if not self.available or self._thread is not None:
            return
        self.reset()
        self._thread = threading.Thread(target=self._worker, name="live-analysis", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        while True:
            try:
                self._queue.put(_STOP, timeout=0.1)
                break
            except queue.Full:
                self._discard_queued()
        self._thread.join(timeout=2.0)
        self._thread = None

    # --- inputs (event loop thread) -----------------------------------------

    def on_frame(self, frame: Frame, raw: bytes = b"") -> None:
        """Receiver handler: cheap, never blocks."""
        if not frame.is_race_on or self._thread is None:
            return
        key = (frame.car_ordinal, frame.track_ordinal)
        if key != self._car_key:
            self._car_key = key
            self._drivetrain = frame.drivetrain
            self.reset()
        try:
            self._queue.put_nowait((self._generation, frame))
        except queue.Full:
            self.dropped_frames += 1

    def reset(self) -> dict[str, Any]:
        """Rebuild the analyzer with the current drivetrain; returns its snapshot."""
        module = self.module.require()
        unit_system = self.unit_system()
        with self._lock:
            self._generation += 1
            self._analyzer = module.LiveAnalyzer(self._drivetrain, unit_system=unit_system)
            snapshot = to_dict(self._analyzer.snapshot())
            self._latest = snapshot
            self._dirty = True
            self.resets += 1
        return snapshot

    def snapshot(self) -> dict[str, Any]:
        self.module.require()
        with self._lock:
            if self._analyzer is None:
                raise AnalysisUnavailable("live analyzer is not running")
            if self._latest is None:
                self._latest = to_dict(self._analyzer.snapshot())
            return self._latest

    # --- output (broadcaster) -----------------------------------------------

    def poll(self, now: float | None = None) -> dict[str, Any] | None:
        """A changed snapshot to broadcast, honouring the rate limit, or None."""
        now = time.monotonic() if now is None else now
        with self._lock:
            if not self._dirty or self._latest is None:
                return None
            if self._last_sent_at is not None and now - self._last_sent_at < self.min_interval_s:
                return None
            self._dirty = False
            if self._latest == self._last_sent:
                return None
            self._last_sent = self._latest
            self._last_sent_at = now
            return self._latest

    def wait_idle(self, timeout: float = 2.0) -> bool:
        """Wait until queued frames are processed (tests and tools)."""
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks:
            if time.monotonic() > deadline:
                return False
            time.sleep(0.002)
        return True

    # --- worker thread ------------------------------------------------------

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is _STOP:
                    return
                generation, frame = item
                with self._lock:
                    if generation != self._generation or self._analyzer is None:
                        continue
                    try:
                        result = self._analyzer.push(frame)
                    except Exception:
                        log.exception("live analyzer push failed")
                        continue
                    if result is not None:
                        self._latest = to_dict(result)
                        self._dirty = True
            finally:
                self._queue.task_done()

    def _discard_queued(self) -> None:
        try:
            while True:
                self._queue.get_nowait()
                self._queue.task_done()
        except queue.Empty:
            pass
