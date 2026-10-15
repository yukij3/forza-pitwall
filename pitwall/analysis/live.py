"""Live tuning board: rolling ratings over the last few corners.

Feed every frame to :meth:`LiveAnalyzer.push`. Per frame it only converts the
frame and advances a few state machines; the real work (judging a corner,
braking zone or straight and re-rating the board) happens when one of those
completes, a few times per lap. Corner detection, per-corner analysis, item
bands and the rulebook are the same ones the per-lap analysis uses.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping

from pitwall.telemetry.model import Frame

from .assess import Evidence, assess_all, build_board
from .records import (
    BottomingEvent,
    BrakeRecord,
    BrakeWindow,
    CornerRecord,
    CornerWindow,
    StraightRecord,
    analyze_brake,
    analyze_corner,
)
from .results import LiveAnalysis, drivetrain_name
from .samples import Sample, SampleBuilder, f_to_c
from .segments import Segmenter
from .thresholds import TIRE_MIN_SECONDS
from .yaw import YawFit

STRAIGHTS_KEPT = 6  # straights considered for the gearing item
TIRE_CHUNK_S = 1.0
TIRE_WINDOW_MIN_S = 60.0  # tire temperatures average at least this much recent driving
_MAX_FORWARD_GEAR = 10


class LiveAnalyzer:
    """Incremental, rolling handling analysis for the live board."""

    def __init__(
        self,
        drivetrain: int | str,
        tune_values: Mapping[str, float] | None = None,
        unit_system: str = "imperial",
        window_corners: int = 12,
    ) -> None:
        self.drivetrain = drivetrain_name(drivetrain)
        self.tune_values = dict(tune_values or {})
        self.unit_system = unit_system
        self.window_corners = max(1, int(window_corners))
        self.reset()

    # -- public -------------------------------------------------------------------
    def reset(self) -> None:
        """Forget the window (call after a tune change)."""
        self._builder = SampleBuilder()
        self._seg = Segmenter()
        self._fit = YawFit()
        self._corners: deque[CornerRecord] = deque(maxlen=self.window_corners)
        self._brakes: deque[BrakeRecord] = deque(maxlen=self.window_corners)
        self._straights: deque[StraightRecord] = deque(maxlen=STRAIGHTS_KEPT)
        self._bottoming: deque[BottomingEvent] = deque()
        self._tire_chunks: deque[tuple[float, float, float, float, float, float]] = deque()
        self._chunk = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]  # 4 temp sums (°F), n, seconds
        self._top_gear = 0
        self._corners_seen = 0
        self._status: dict[str, str] = {}
        self._lap: int | None = None
        self._lap_start_dist: float | None = None
        self._lap_length: float | None = None
        self._last: Sample | None = None
        self._snapshot = self._build()

    def push(self, frame: Frame) -> LiveAnalysis | None:
        """Feed one frame; returns a new snapshot when the board was re-rated."""
        if not frame.is_race_on:
            return None
        s = self._builder.push(frame)
        if s is None:
            return None
        self._last = s
        self._fit.add(s)

        chunk = self._chunk
        t = s.temps
        chunk[0] += t[0]
        chunk[1] += t[1]
        chunk[2] += t[2]
        chunk[3] += t[3]
        chunk[4] += 1
        chunk[5] += s.dt
        if chunk[5] >= TIRE_CHUNK_S:
            self._tire_chunks.append((s.t, *chunk[:4], chunk[4]))
            self._chunk = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

        if self._top_gear < s.gear <= _MAX_FORWARD_GEAR:
            self._top_gear = s.gear
        if s.lap != self._lap:
            if (
                self._lap is not None
                and s.lap == self._lap + 1
                and self._lap_start_dist is not None
            ):
                self._lap_length = s.dist - self._lap_start_dist
            if self._lap is not None:
                self._lap_start_dist = s.dist
            self._lap = s.lap

        segs = self._seg.push(s)
        if not segs:
            return None
        changed = False
        for seg in segs:
            changed = self._take(seg) or changed
        if not changed:
            return None
        self._snapshot = self._build()
        return self._snapshot

    def snapshot(self) -> LiveAnalysis:
        return self._snapshot

    # -- internals ----------------------------------------------------------------
    def _take(self, seg: object) -> bool:
        if isinstance(seg, CornerWindow):
            rec = analyze_corner(
                seg, self._fit.model(), self.drivetrain, self._fit.steer_sign, self._fit.yaw_sign
            )
            if rec.partial:
                return False
            self._corners_seen += 1
            rec.number = self._corners_seen
            self._corners.append(rec)
            return True
        if isinstance(seg, BrakeWindow):
            rec_b = analyze_brake(seg)
            if rec_b.partial:
                return False
            self._brakes.append(rec_b)
            return True
        if isinstance(seg, StraightRecord):
            if seg.cut_end:
                return False
            self._straights.append(seg)
            return True
        if isinstance(seg, BottomingEvent):
            self._bottoming.append(seg)
            return True
        return False

    def _window_start(self) -> float | None:
        return self._corners[0].t_start if self._corners else None

    def _tire_avg(self, now: float) -> tuple[tuple[float, float, float, float] | None, float]:
        start = self._window_start()
        horizon = now - TIRE_WINDOW_MIN_S
        if start is not None:
            horizon = min(horizon, start)
        chunks = self._tire_chunks
        while chunks and chunks[0][0] < horizon:
            chunks.popleft()
        n = sum(c[5] for c in chunks)
        if not n:
            return None, 0.0
        seconds = len(chunks) * TIRE_CHUNK_S
        avg = tuple(f_to_c(sum(c[k] for c in chunks) / n) for k in range(1, 5))
        return avg, seconds  # type: ignore[return-value]

    def _build(self) -> LiveAnalysis:
        now = self._last.t if self._last is not None else 0.0
        start = self._window_start()
        if start is not None:
            while self._bottoming and self._bottoming[0].t < start:
                self._bottoming.popleft()
        tire_avg, tire_s = self._tire_avg(now)
        ev = Evidence(
            corners=list(self._corners),
            brakes=list(self._brakes),
            straights=list(self._straights),
            bottoming=list(self._bottoming),
            tire_avg_c=tire_avg if tire_s >= TIRE_MIN_SECONDS else None,
            tire_seconds=tire_s,
            top_gear=self._top_gear,
            drivetrain=self.drivetrain,
        )
        items, focus = build_board(
            assess_all(ev),
            drivetrain=self.drivetrain,
            unit_system=self.unit_system,
            tune_values=self.tune_values,
            previous=self._status,
        )
        window_laps = None
        if self._corners and self._lap_length and self._last is not None:
            span = self._last.dist - self._corners[0].start_dist
            window_laps = span / self._lap_length
        return LiveAnalysis(
            corners_seen=self._corners_seen,
            window_corners=len(self._corners),
            window_laps=window_laps,
            focus=focus,
            items=tuple(items),
        )
