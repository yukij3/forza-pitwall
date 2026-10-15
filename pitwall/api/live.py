"""Live WebSocket broadcaster for ``/ws/live``.

Each client gets a bounded queue (oldest messages are dropped if a client is
slow). A loop running at ``live_hz`` sends the latest telemetry frame, status
(on change and at least once per second) and live-analysis snapshots.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from pitwall.api.convert import telemetry_message
from pitwall.services.live_analysis import LiveAnalysisService
from pitwall.telemetry.model import Frame

log = logging.getLogger(__name__)

CLIENT_QUEUE_SIZE = 256
STATUS_INTERVAL_S = 1.0

StatusProvider = Callable[[], dict[str, Any]]


def status_signature(status: dict[str, Any]) -> tuple[Any, ...]:
    """The parts of Status whose change is worth an immediate push."""
    receiver = status["receiver"]
    age = receiver.get("last_packet_age_s")
    return (
        receiver.get("listening"),
        receiver.get("race_on"),
        age is not None and age < 2.0,
        tuple(sorted(status["recording"].items())),
        tuple(sorted((status.get("car") or {}).items())),
        status.get("track_ordinal"),
    )


class LiveHub:
    def __init__(
        self,
        status_provider: StatusProvider,
        *,
        live_hz: float = 20.0,
        live_analysis: LiveAnalysisService | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.status_provider = status_provider
        self.live_hz = live_hz
        self.live_analysis = live_analysis
        self.clock = clock
        self._clients: set[asyncio.Queue[dict[str, Any]]] = set()
        self._latest: Frame | None = None
        self._seq = 0
        self._sent_seq = 0
        self._t0 = clock()
        self._status_dirty = False
        self._last_status_at = 0.0
        self._last_signature: tuple[Any, ...] | None = None

    @property
    def client_count(self) -> int:
        return len(self._clients)

    # --- inputs -------------------------------------------------------------

    def on_frame(self, frame: Frame, raw: bytes = b"") -> None:
        self._latest = frame
        self._seq += 1

    def notify_status(self) -> None:
        self._status_dirty = True

    def publish(self, message: dict[str, Any]) -> None:
        for q in self._clients:
            _put_drop_oldest(q, message)

    # --- loop ---------------------------------------------------------------

    async def run(self) -> None:
        interval = 1.0 / self.live_hz
        while True:
            try:
                self.tick()
            except Exception:
                log.exception("live hub tick failed")
            await asyncio.sleep(interval)

    def tick(self, now: float | None = None) -> None:
        now = self.clock() if now is None else now
        if self.live_analysis is not None and self.live_analysis.available:
            update = self.live_analysis.poll(now)
            if update is not None:
                self.publish({"type": "live_analysis", **update})
        if not self._clients:
            return
        frame = self._latest
        if frame is not None and self._seq != self._sent_seq:
            self._sent_seq = self._seq
            self.publish(telemetry_message(frame, frame.recv_time - self._t0))
        status = self.status_provider()
        signature = status_signature(status)
        if (
            self._status_dirty
            or signature != self._last_signature
            or now - self._last_status_at >= STATUS_INTERVAL_S
        ):
            self._status_dirty = False
            self._last_signature = signature
            self._last_status_at = now
            self.publish({"type": "status", **status})

    # --- websocket ----------------------------------------------------------

    async def serve(self, websocket: WebSocket) -> None:
        await websocket.accept()
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=CLIENT_QUEUE_SIZE)
        self._clients.add(q)
        waiter = asyncio.create_task(_wait_disconnect(websocket))
        try:
            await websocket.send_json({"type": "status", **self.status_provider()})
            if self.live_analysis is not None and self.live_analysis.available:
                with contextlib.suppress(Exception):
                    snapshot = self.live_analysis.snapshot()
                    await websocket.send_json({"type": "live_analysis", **snapshot})
            while True:
                getter = asyncio.create_task(q.get())
                done, _ = await asyncio.wait({getter, waiter}, return_when=asyncio.FIRST_COMPLETED)
                if waiter in done:
                    getter.cancel()
                    break
                await websocket.send_json(getter.result())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            self._clients.discard(q)
            waiter.cancel()
            if waiter.done() and not waiter.cancelled():
                waiter.exception()  # retrieved, so asyncio doesn't log it


async def _wait_disconnect(websocket: WebSocket) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return


def _put_drop_oldest(q: asyncio.Queue[dict[str, Any]], message: dict[str, Any]) -> None:
    if q.full():
        with contextlib.suppress(asyncio.QueueEmpty):
            q.get_nowait()
    with contextlib.suppress(asyncio.QueueFull):
        q.put_nowait(message)
