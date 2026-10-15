"""UDP receiver for Data Out packets.

Parses every datagram, keeps simple stats and fans the frame out to handlers
(recorder, live broadcaster). Unsupported packet sizes are counted and dropped.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from pitwall.telemetry.model import Frame
from pitwall.telemetry.packet import PacketError, parse

log = logging.getLogger(__name__)

FrameHandler = Callable[[Frame, bytes], None]

RATE_WINDOW_S = 1.0
RACE_ON_STALE_S = 2.0  # race_on reads false when packets stopped this long ago


@dataclass(frozen=True, slots=True)
class ReceiverStats:
    packets_per_sec: float
    last_packet_age_s: float | None
    race_on: bool
    total_packets: int
    ignored_packets: int
    last_ignored_size: int | None


class TelemetryReceiver(asyncio.DatagramProtocol):
    def __init__(
        self,
        handlers: list[FrameHandler] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.handlers: list[FrameHandler] = list(handlers or [])
        self.clock = clock
        self.last_frame: Frame | None = None
        self.last_race_frame: Frame | None = None  # car/track info survives menus
        self.listening = False
        self._last_recv: float | None = None
        self._recent: deque[float] = deque(maxlen=2000)
        self._total = 0
        self._ignored = 0
        self._last_ignored_size: int | None = None
        self._transport: asyncio.DatagramTransport | None = None

    # --- asyncio protocol ---------------------------------------------------

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = transport  # type: ignore[assignment]
        self.listening = True

    def connection_lost(self, exc: Exception | None) -> None:
        self.listening = False

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.handle_packet(data)

    def error_received(self, exc: Exception) -> None:
        log.warning("UDP receive error: %s", exc)

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        self.listening = False

    # --- packet handling ----------------------------------------------------

    def handle_packet(self, data: bytes, recv_time: float | None = None) -> Frame | None:
        """Parse one datagram and pass it to the handlers. Returns the frame."""
        now = self.clock() if recv_time is None else recv_time
        try:
            frame = parse(data, now)
        except PacketError:
            self._ignored += 1
            self._last_ignored_size = len(data)
            return None
        self._total += 1
        self._last_recv = now
        self._recent.append(now)
        self.last_frame = frame
        if frame.is_race_on:
            self.last_race_frame = frame
        for handler in self.handlers:
            try:
                handler(frame, data)
            except Exception:
                log.exception("telemetry handler failed")
        return frame

    def stats(self, now: float | None = None) -> ReceiverStats:
        now = self.clock() if now is None else now
        recent = self._recent
        while recent and recent[0] < now - RATE_WINDOW_S:
            recent.popleft()
        age = None if self._last_recv is None else max(0.0, now - self._last_recv)
        race_on = bool(
            self.last_frame is not None
            and self.last_frame.is_race_on
            and age is not None
            and age < RACE_ON_STALE_S
        )
        return ReceiverStats(
            packets_per_sec=len(recent) / RATE_WINDOW_S,
            last_packet_age_s=age,
            race_on=race_on,
            total_packets=self._total,
            ignored_packets=self._ignored,
            last_ignored_size=self._last_ignored_size,
        )


async def start_udp(receiver: TelemetryReceiver, host: str, port: int) -> asyncio.DatagramTransport:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(lambda: receiver, local_addr=(host, port))
    return transport
