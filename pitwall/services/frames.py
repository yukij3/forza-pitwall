"""Load a lap's frames back from the session's raw packet file (with a small cache)."""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

from pitwall.storage.db import Store
from pitwall.storage.rawlog import iter_records
from pitwall.telemetry.model import Frame
from pitwall.telemetry.packet import PacketError, parse


class LapFrames:
    def __init__(self, store: Store, maxsize: int = 16) -> None:
        self.store = store
        self.maxsize = maxsize
        self._cache: OrderedDict[int, list[Frame]] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, lap_id: int, frames: list[Frame]) -> None:
        with self._lock:
            self._cache[lap_id] = frames
            self._cache.move_to_end(lap_id)
            while len(self._cache) > self.maxsize:
                self._cache.popitem(last=False)

    def get(self, lap: dict[str, Any]) -> list[Frame]:
        lap_id = int(lap["id"])
        with self._lock:
            cached = self._cache.get(lap_id)
            if cached is not None:
                self._cache.move_to_end(lap_id)
                return cached
        frames = self._load(lap)
        self.put(lap_id, frames)
        return frames

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def _load(self, lap: dict[str, Any]) -> list[Frame]:
        session = self.store.get_session(int(lap["session_id"]))
        path = self.store.raw_path(session)
        if path is None or not path.exists():
            return []
        frames: list[Frame] = []
        for recv_time, payload in iter_records(path, lap["first_frame"], lap["frame_count"]):
            try:
                frames.append(parse(payload, recv_time))
            except PacketError:
                continue
        return frames
