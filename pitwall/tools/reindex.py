"""Rebuild laps (and cached analysis) of recorded sessions from their raw packets.

Use it after an update that changes how laps are cut or analysed:
``python -m pitwall reindex``. Sessions that are still recording are skipped.
It is safe to run while the server runs; restart the server afterwards so it
drops laps it may still hold in memory.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pitwall.services.analysis_runner import AnalysisRunner
from pitwall.services.frames import LapFrames
from pitwall.services.recorder import lap_fields
from pitwall.storage.db import Store
from pitwall.storage.rawlog import iter_records, raw_version
from pitwall.telemetry.laps import GAP_S, LapSegment, LapSegmenter
from pitwall.telemetry.packet import PacketError, parse

log = logging.getLogger(__name__)


@dataclass
class SessionResult:
    session_id: int
    before: list[dict[str, Any]] = field(default_factory=list)
    after: list[dict[str, Any]] = field(default_factory=list)
    skipped: str | None = None
    analysis: str | None = None


def resegment(
    records: Iterable[tuple[float, bytes]], *, version: int, wall_start: float
) -> list[LapSegment]:
    """Cut laps from raw records the way the recorder does live.

    Version 1 files have no race-off markers, so a gap of more than
    :data:`GAP_S` between race-on packets is taken as the game leaving the
    race (menu, pause or rewind screen).
    """
    first_recv: float | None = None
    recv_now = 0.0

    def wall_clock() -> float:
        return wall_start + (recv_now - (first_recv or 0.0))

    segmenter = LapSegmenter(wall_clock=wall_clock)
    laps: list[LapSegment] = []
    last_on: float | None = None
    for index, (recv_time, payload) in enumerate(records):
        try:
            frame = parse(payload, recv_time)
        except PacketError:
            continue
        if first_recv is None:
            first_recv = recv_time
        recv_now = recv_time
        if not frame.is_race_on:
            laps += segmenter.note_race_off()
            continue
        if version == 1 and last_on is not None and recv_time - last_on > GAP_S:
            laps += segmenter.note_race_off()
        last_on = recv_time
        laps += segmenter.add(frame, index)
    return laps + segmenter.finish()


def reindex(
    store: Store,
    session_ids: Sequence[int] | None = None,
    *,
    analyze: bool = True,
    dry_run: bool = False,
) -> list[SessionResult]:
    wanted = set(session_ids) if session_ids else None
    sessions = [s for s in reversed(store.list_sessions()) if wanted is None or s["id"] in wanted]
    runner = AnalysisRunner(store, LapFrames(store)) if analyze and not dry_run else None
    results: list[SessionResult] = []
    try:
        for session in sessions:
            results.append(_reindex_session(store, session, runner, dry_run=dry_run))
    finally:
        if runner is not None:
            runner.close()
    return results


def _reindex_session(
    store: Store, session: dict[str, Any], runner: AnalysisRunner | None, *, dry_run: bool
) -> SessionResult:
    result = SessionResult(session_id=int(session["id"]), before=store.list_laps(session["id"]))
    path = store.raw_path(session)
    if session["stopped_at"] is None:
        result.skipped = "still recording"
        return result
    if path is None or not path.exists():
        result.skipped = "raw packet file missing"
        return result
    wall_start = _epoch(session["started_at"])
    segments = resegment(iter_records(path), version=raw_version(path), wall_start=wall_start)
    result.after = [lap_fields(seg) for seg in segments]
    if dry_run:
        return result
    new_laps = store.replace_laps(result.session_id, result.after)
    result.after = new_laps
    if runner is not None:
        result.analysis = _analyze(runner, result.session_id, new_laps)
    return result


def _analyze(runner: AnalysisRunner, session_id: int, laps: list[dict[str, Any]]) -> str:
    if not runner.available:
        return "analysis engine not installed"
    try:
        for lap in laps:
            runner.lap_sync(int(lap["id"]))
        if laps:
            runner.session_sync(session_id)
    except Exception as exc:  # report and carry on with the next session
        log.exception("analysis of session %s failed", session_id)
        return f"analysis failed: {exc}"
    return f"analysed {len(laps)} lap(s)"


def _epoch(stamp: str) -> float:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


# --- report ----------------------------------------------------------------------


def format_laps(laps: Sequence[dict[str, Any]]) -> list[str]:
    rows = [f"  {'lap':>3}  {'kind':<7} {'valid':<5} {'reason':<9} {'time':>9} {'frames':>7}"]
    for lap in laps:
        time = "" if lap["lap_time"] is None else f"{lap['lap_time']:.3f}"
        rows.append(
            f"  {lap['number']:>3}  {lap['kind']:<7} {str(bool(lap['valid'])).lower():<5} "
            f"{lap['invalid_reason'] or '':<9} {time:>9} {lap['frame_count']:>7}"
        )
    return rows


def report(results: Sequence[SessionResult], out: Callable[[str], None] = print) -> None:
    for r in results:
        out(f"session {r.session_id}" + (f": skipped ({r.skipped})" if r.skipped else ""))
        if r.skipped:
            continue
        out(" before:")
        for line in format_laps(r.before):
            out(line)
        out(" after:")
        for line in format_laps(r.after):
            out(line)
        if r.analysis:
            out(f" {r.analysis}")


def run(data_dir: Path, session_ids: Sequence[int] | None, *, analyze: bool, dry_run: bool) -> int:
    store = Store(data_dir)
    try:
        results = reindex(store, session_ids, analyze=analyze, dry_run=dry_run)
    finally:
        store.close()
    report(results)
    if dry_run:
        print("dry run: nothing was written")
    return 0
