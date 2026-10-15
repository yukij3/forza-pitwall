"""Paced UDP sending shared by the simulator and replay."""

from __future__ import annotations

import socket
import time
from collections.abc import Iterable


def pace(
    packets: Iterable[tuple[float, bytes]],
    host: str,
    port: int,
    *,
    speedup: float = 1.0,
) -> int:
    """Send ``(timestamp_s, payload)`` pairs keeping their relative timing.

    ``speedup`` > 1 plays faster. Returns the number of packets sent.
    """
    if speedup <= 0:
        raise ValueError("speedup must be positive")
    sent = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        start = time.monotonic()
        first: float | None = None
        for stamp, payload in packets:
            if first is None:
                first = stamp
            delay = start + (stamp - first) / speedup - time.monotonic()
            if delay > 0.001:
                time.sleep(delay)
            sock.sendto(payload, (host, port))
            sent += 1
    return sent
