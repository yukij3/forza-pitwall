"""Split a stream of race-on frames into laps.

Pure state machine, no I/O. The recorder feeds it every race-on frame in order
(with the frame's index in the session's raw packet file) and tells it when it
saw a race-off frame. It returns finished laps as :class:`LapSegment` objects.

Rules (documented for users in ``docs/storage.md``):

* A lap ends when ``lap_number`` changes. A forward change is a line crossing.
* ``lap_time`` comes from ``last_lap`` once the game updates it after the line;
  if it doesn't within :data:`FINALIZE_FRAMES`, the last ``current_lap`` is used.
* Kinds: ``partial`` if the lap's start wasn't observed; ``out`` if it was
  complete but started from (nearly) standstill; ``flying`` if complete;
  ``in`` if it started at the line but ended without crossing it while the
  game had stopped the race or the car was nearly stopped; otherwise ``partial``.
* Invalid if a rewind (``current_lap`` or ``distance_traveled`` going
  backwards), a pause (race-off frames in the middle), a data gap, or partial.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from pitwall.telemetry.model import Frame

LapKind = Literal["out", "flying", "in", "partial"]

START_TOLERANCE_S = 1.0  # first frame's current_lap below this = lap start observed
STANDING_START_SPEED = 10.0  # m/s; a complete lap starting slower is an out lap
IN_LAP_SPEED = 5.0  # m/s; an unfinished lap ending slower is an in lap
REWIND_TIME_S = 0.05  # current_lap going back more than this = rewind
REWIND_DISTANCE_M = 5.0  # distance_traveled going back more than this = rewind
GAP_S = 1.0  # no packets for longer than this inside a lap = data gap
FINALIZE_FRAMES = 30  # frames to wait for last_lap to update after the line
MIN_TRAILING_FRAMES = 60  # unfinished laps shorter than this are dropped at stop


@dataclass(eq=False)
class LapSegment:
    lap_number: int  # raw game lap number (0-based)
    first_index: int  # index of the first frame in the session's raw packet file
    started_wall: float  # wall clock (epoch seconds) when the first frame arrived
    started_at_line: bool
    frames: list[Frame] = field(default_factory=list)
    ended_at_line: bool = False
    ended_by_race_off: bool = False
    lap_time: float | None = None
    invalid_reasons: list[str] = field(default_factory=list)

    @property
    def number(self) -> int:
        """1-based lap number, as shown on the game HUD."""
        return self.lap_number + 1

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    @property
    def kind(self) -> LapKind:
        if not self.started_at_line:
            return "partial"
        if self.ended_at_line:
            return "out" if self.frames[0].speed < STANDING_START_SPEED else "flying"
        if self.ended_by_race_off or self.frames[-1].speed < IN_LAP_SPEED:
            return "in"
        return "partial"

    @property
    def valid(self) -> bool:
        return self.invalid_reason is None

    @property
    def invalid_reason(self) -> str | None:
        if self.invalid_reasons:
            return self.invalid_reasons[0]
        if self.kind == "partial":
            return "partial"
        return None

    def invalidate(self, reason: str) -> None:
        if reason not in self.invalid_reasons:
            self.invalid_reasons.append(reason)


@dataclass(eq=False)
class _Pending:
    segment: LapSegment
    last_lap_before: float
    estimate: float
    waited: int = 0


class LapSegmenter:
    def __init__(self, wall_clock: Callable[[], float] = time.time) -> None:
        self._wall_clock = wall_clock
        self.current: LapSegment | None = None
        self._pending: _Pending | None = None
        self._race_off_seen = False

    def note_race_off(self) -> None:
        """The game sent a race-off packet (menu, pause, rewind screen)."""
        if self.current is not None:
            self._race_off_seen = True

    def add(self, frame: Frame, index: int) -> list[LapSegment]:
        """Feed one race-on frame; returns laps finished by it (oldest first)."""
        done: list[LapSegment] = []
        cur = self.current
        if cur is None:
            self._start(frame, index, at_line=frame.current_lap < START_TOLERANCE_S)
        else:
            prev = cur.frames[-1]
            if self._race_off_seen:
                self._race_off_seen = False
                cur.invalidate("pause")
            if frame.lap_number > prev.lap_number:
                done += self._flush_pending(force=True)
                cur.ended_at_line = True
                self._pending = _Pending(cur, prev.last_lap, prev.current_lap)
                self._start(frame, index, at_line=True)
            elif frame.lap_number < prev.lap_number:
                # Rewound (or restarted) across the line.
                done += self._flush_pending(force=True)
                cur.invalidate("rewind")
                done.append(cur)
                self._start(frame, index, at_line=frame.current_lap < START_TOLERANCE_S)
            else:
                if (
                    frame.current_lap < prev.current_lap - REWIND_TIME_S
                    or frame.distance_traveled < prev.distance_traveled - REWIND_DISTANCE_M
                ):
                    cur.invalidate("rewind")
                if frame.recv_time - prev.recv_time > GAP_S:
                    cur.invalidate("data_gap")
                cur.frames.append(frame)
        done += self._check_pending(frame)
        return done

    def finish(self) -> list[LapSegment]:
        """Stop: finalize the pending lap and close the open one."""
        done = self._flush_pending(force=True)
        cur = self.current
        if cur is not None and cur.frame_count >= MIN_TRAILING_FRAMES:
            cur.ended_by_race_off = self._race_off_seen
            done.append(cur)
        self.current = None
        self._race_off_seen = False
        return done

    def _start(self, frame: Frame, index: int, *, at_line: bool) -> None:
        self.current = LapSegment(
            lap_number=frame.lap_number,
            first_index=index,
            started_wall=self._wall_clock(),
            started_at_line=at_line,
            frames=[frame],
        )

    def _check_pending(self, frame: Frame) -> list[LapSegment]:
        pending = self._pending
        if pending is None:
            return []
        if frame.last_lap > 0 and frame.last_lap != pending.last_lap_before:
            pending.segment.lap_time = frame.last_lap
            self._pending = None
            return [pending.segment]
        pending.waited += 1
        if pending.waited >= FINALIZE_FRAMES:
            return self._flush_pending(force=True)
        return []

    def _flush_pending(self, *, force: bool) -> list[LapSegment]:
        pending = self._pending
        if pending is None or not force:
            return []
        self._pending = None
        if pending.segment.lap_time is None and pending.estimate > 0:
            pending.segment.lap_time = pending.estimate
        return [pending.segment]
