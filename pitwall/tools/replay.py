"""Resend a recorded session's raw packets at their original timing."""

from __future__ import annotations

from pathlib import Path

from pitwall.storage.rawlog import iter_records
from pitwall.tools.udp import pace


def replay(path: Path, host: str, port: int, *, speedup: float = 1.0) -> int:
    return pace(iter_records(path), host, port, speedup=speedup)
