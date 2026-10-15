"""Split a stream of race-on frames into laps.

Pure state machine, no I/O, no assumption about the packet rate (the game
sends 60 to 160+ packets per second depending on the platform). The recorder
feeds it every race-on frame in order, with the frame's index in the
session's raw packet file, and tells it when it saw a race-off packet. It
returns finished laps as :class:`LapSegment` objects.

Patterns seen in real recordings, and how they are handled:

* **Pre-race**: before the start the lap timer reads exactly 0. Such frames
  belong to no lap.
* **Grid start**: the timer runs from the lights, then restarts at 0 when the
  car first crosses the start line (the grid is behind it) while
  ``LapNumber`` stays 0. That restart is a line crossing; the short run-up
  before it is not a lap and is dropped.
* **Rewind**: the game sends race-off packets while the rewind screen is up,
  then the race clock, lap timer and distance resume from an earlier point.
  Going backwards wins over the pause, so the lap is marked ``rewind``.
* **Race finish**: at the chequered flag the game turns ``IsRaceOn`` off
  without incrementing ``LapNumber``. A lap that ends within
  :data:`FINISH_TOLERANCE_M` of where the line should be is complete; its time
  is the last lap-timer value. The lap length comes from an earlier lap, or
  before that from the pre-race packets, whose distance reads minus one lap.
* **Quitting mid-lap**: race-off at speed away from the line; the lap is
  ``partial``.

Kinds: ``partial`` if the lap's start or end wasn't observed; ``out`` if
complete but started from (nearly) standstill; ``flying`` if complete; ``in``
if it started at the line and ended with the car nearly stopped (pits).
Invalid if a rewind, a pause (race-off packets in the middle and the race
clock carried on), a data gap, or partial.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from pitwall.telemetry.model import Frame

LapKind = Literal["out", "flying", "in", "partial"]

START_TOLERANCE_S = 1.0  # lap timer below this on the first frame = lap start observed
STANDING_START_SPEED = 10.0  # m/s; a complete lap starting slower is an out lap
IN_LAP_SPEED = 5.0  # m/s; an unfinished lap ending slower is an in lap
REWIND_TIME_S = 0.05  # race clock / lap timer going back more than this = rewind
REWIND_DISTANCE_M = 5.0  # distance going back more than this = rewind
GAP_S = 1.0  # no packets for longer than this inside a lap = data gap
FINALIZE_S = 0.5  # how long to wait for LastLap to update after the line
MIN_SEGMENT_S = 1.0  # incomplete laps shorter than this are dropped
MIN_LAP_S = 20.0  # a "lap" ended by a timer restart shorter than this is a grid run-up
FINISH_TOLERANCE_M = 20.0  # race-off this close to the line completes the lap
SAME_TIME_S = 0.05  # unchanged LastLap this close to the timer is this lap's time


def is_lap_frame(frame: Frame) -> bool:
    """Frames that can belong to a lap: race on and the lap timer running."""
    return frame.is_race_on and frame.current_lap != 0.0


@dataclass(eq=False)
class LapSegment:
    lap_number: int  # raw game lap number (0-based)
    first_index: int  # raw-file index of the first frame
    started_wall: float  # wall clock (epoch seconds) when the first frame arrived
    started_at_line: bool
    frames: list[Frame] = field(default_factory=list)
    last_index: int = 0  # raw-file index of the last frame
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
    def duration(self) -> float:
        """Lap-timer seconds covered (game time, independent of the packet rate)."""
        return max(0.0, self.frames[-1].current_lap - self.frames[0].current_lap)

    @property
    def kind(self) -> LapKind:
        if not self.started_at_line:
            return "partial"
        if self.ended_at_line:
            return "out" if self.frames[0].speed < STANDING_START_SPEED else "flying"
        if self.frames[-1].speed < IN_LAP_SPEED:
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

    def append(self, frame: Frame, index: int) -> None:
        self.frames.append(frame)
        self.last_index = index


@dataclass(eq=False)
class _Pending:
    segment: LapSegment
    last_lap_before: float  # LastLap before the line, to see when it updates
    estimate: float  # lap timer on the last frame before the line
    since: float  # recv_time of the crossing
    latest_last_lap: float = 0.0


class LapSegmenter:
    def __init__(self, wall_clock: Callable[[], float] = time.time) -> None:
        self._wall_clock = wall_clock
        self.current: LapSegment | None = None
        self.measured_length: float | None = None  # metres, from the last complete lap
        self.grid_length: float | None = None  # metres, from pre-race packets
        self._pending: _Pending | None = None
        self._race_off_seen = False

    # --- inputs -------------------------------------------------------------

    def add(self, frame: Frame, index: int) -> list[LapSegment]:
        """Feed one race-on frame; returns laps finished by it (oldest first)."""
        if not is_lap_frame(frame):
            # Pre-race: the lap timer isn't running yet. On the grid the game
            # reports the distance as minus one lap.
            if frame.is_race_on and frame.distance_traveled < -100.0:
                self.grid_length = -frame.distance_traveled
            return []
        done: list[LapSegment] = []
        cur = self.current
        if cur is None:
            self._race_off_seen = False
            self._start(frame, index, at_line=frame.current_lap < START_TOLERANCE_S)
            return done + self._check_pending(frame)

        prev = cur.frames[-1]
        resumed = self._race_off_seen
        self._race_off_seen = False
        if frame.lap_number > prev.lap_number:
            done += self._flush_pending()
            self._close_at_line(cur, prev, frame, resumed=resumed)
            self._start(frame, index, at_line=True)
        elif frame.lap_number < prev.lap_number:
            done += self._flush_pending()
            if frame.current_race_time >= START_TOLERANCE_S:
                cur.invalidate("rewind")  # rewound back across the line
                done += self._close_unfinished(cur, race_off=False)
            else:  # race restarted (possibly another track)
                done += self._close_unfinished(cur, race_off=True)
                self.measured_length = None
            self._start(frame, index, at_line=frame.current_lap < START_TOLERANCE_S)
        elif _timer_restarted(prev, frame):
            # Lap timer back to 0 at the line without a lap-number change: the
            # first crossing after a grid start. A short segment before it is
            # the run-up from the grid, not a lap.
            done += self._flush_pending()
            if cur.started_at_line and cur.duration >= MIN_LAP_S:
                self._close_at_line(cur, prev, frame, resumed=resumed)
                done += self._flush_pending()
            self._start(frame, index, at_line=True)
        else:
            if _went_back(prev, frame):
                cur.invalidate("rewind")
            elif resumed:
                cur.invalidate("pause")
            elif frame.recv_time - prev.recv_time > GAP_S:
                cur.invalidate("data_gap")
            cur.append(frame, index)
        return done + self._check_pending(frame)

    def note_race_off(self) -> list[LapSegment]:
        """The game sent a race-off packet (menus, pause, rewind screen, finish).

        Returns the open lap if this ends it at the finish line.
        """
        cur = self.current
        if cur is None:
            return []
        self._race_off_seen = True
        if self._at_finish(cur):
            done = self._flush_pending()
            self.current = None
            self._race_off_seen = False
            return done + self._close_unfinished(cur, race_off=True)
        return []

    def finish(self) -> list[LapSegment]:
        """Stop: finalize the pending lap and close the open one."""
        done = self._flush_pending()
        cur = self.current
        if cur is not None:
            done += self._close_unfinished(cur, race_off=self._race_off_seen)
        self.current = None
        self._race_off_seen = False
        return done

    # --- internals ----------------------------------------------------------

    def _start(self, frame: Frame, index: int, *, at_line: bool) -> None:
        self.current = LapSegment(
            lap_number=frame.lap_number,
            first_index=index,
            last_index=index,
            started_wall=self._wall_clock(),
            started_at_line=at_line,
            frames=[frame],
        )

    def _close_at_line(
        self, seg: LapSegment, prev: Frame, crossing: Frame, *, resumed: bool
    ) -> None:
        """The car crossed the line: the lap waits for LastLap to update."""
        if resumed:
            seg.invalidate("pause")
        seg.ended_at_line = True
        if seg.started_at_line:
            self.measured_length = crossing.distance_traveled - seg.frames[0].distance_traveled
        self._pending = _Pending(seg, prev.last_lap, prev.current_lap, crossing.recv_time)

    @property
    def lap_length(self) -> float | None:
        return self.measured_length or self.grid_length

    def _to_line(self, seg: LapSegment) -> float | None:
        """Metres from the lap's last frame to the line, if the lap length is known."""
        length = self.lap_length
        if not seg.started_at_line or length is None:
            return None
        start = seg.frames[0].distance_traveled
        return start + length - seg.frames[-1].distance_traveled

    def _at_finish(self, seg: LapSegment) -> bool:
        remaining = self._to_line(seg)
        return remaining is not None and abs(remaining) <= FINISH_TOLERANCE_M

    def _close_unfinished(self, seg: LapSegment, *, race_off: bool) -> list[LapSegment]:
        """Close a lap that didn't end with a lap-number change."""
        seg.ended_by_race_off = race_off
        remaining = self._to_line(seg)
        if remaining is not None and abs(remaining) <= FINISH_TOLERANCE_M:
            last = seg.frames[-1]  # race finish: the game stopped at the line
            seg.ended_at_line = True
            seg.lap_time = last.current_lap + max(0.0, remaining) / max(last.speed, 1.0)
            return [seg]
        return [seg] if seg.duration >= MIN_SEGMENT_S else []

    def _check_pending(self, frame: Frame) -> list[LapSegment]:
        pending = self._pending
        if pending is None:
            return []
        if frame.last_lap > 0 and frame.last_lap != pending.last_lap_before:
            pending.segment.lap_time = frame.last_lap
            self._pending = None
            return [pending.segment]
        pending.latest_last_lap = frame.last_lap
        if frame.recv_time - pending.since >= FINALIZE_S:
            return self._flush_pending()
        return []

    def _flush_pending(self) -> list[LapSegment]:
        """Finish the lap waiting for LastLap, falling back to the lap timer."""
        pending = self._pending
        if pending is None:
            return []
        self._pending = None
        seg = pending.segment
        if seg.lap_time is None and pending.estimate > 0:
            # LastLap never changed: either this lap took the same time as the
            # previous one (then it agrees with the timer), or it wasn't updated.
            same = abs(pending.latest_last_lap - pending.estimate) <= SAME_TIME_S
            seg.lap_time = pending.latest_last_lap if same else pending.estimate
        return [seg]


def _went_back(prev: Frame, frame: Frame) -> bool:
    """Race clock, lap timer or distance moved backwards (a rewind)."""
    clock_back = (
        prev.current_race_time > 0
        and frame.current_race_time < prev.current_race_time - REWIND_TIME_S
    )
    return (
        clock_back
        or frame.current_lap < prev.current_lap - REWIND_TIME_S
        or frame.distance_traveled < prev.distance_traveled - REWIND_DISTANCE_M
    )


def _timer_restarted(prev: Frame, frame: Frame) -> bool:
    """Lap timer reset to ~0 while the race clock and distance carried on."""
    return (
        frame.current_lap < START_TOLERANCE_S
        and prev.current_lap - frame.current_lap > START_TOLERANCE_S
        and frame.current_race_time >= prev.current_race_time - REWIND_TIME_S
        and frame.distance_traveled >= prev.distance_traveled - REWIND_DISTANCE_M
    )
