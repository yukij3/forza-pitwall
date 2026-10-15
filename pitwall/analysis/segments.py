"""Streaming segmentation of samples into corners, braking zones, straights and
bottoming hits.

The :class:`Segmenter` does O(1) work per sample and only touches its history
buffer when something completes, which keeps the live board cheap. The per-lap
analyzer feeds a whole lap through the same segmenter and calls
:meth:`Segmenter.flush` at the end.

Corner = continuous lateral load: it starts when |lateral g| reaches
``CORNER_ENTER_G`` (backdated to where it first exceeded ``CORNER_EXIT_G``) and
ends when it falls below ``CORNER_EXIT_G``. Same-direction load that resumes
within ``CORNER_MERGE_GAP_S`` continues the corner. A finished corner is emitted
after its exit window (``CORNER_EXIT_WINDOW_S``) or when the next corner starts,
with the braking zone that leads into it.
"""

from __future__ import annotations

from collections import deque
from itertools import islice

from .records import BottomingEvent, BrakeWindow, CornerWindow, StraightRecord
from .samples import Sample
from .thresholds import (
    BOTTOMING_MERGE_S,
    BOTTOMING_MIN_SPEED,
    BOTTOMING_TRAVEL,
    BRAKE_LOOKBACK_S,
    BRAKE_ON,
    BRAKE_RELEASE_GAP_S,
    BRAKE_ZONE_MIN_S,
    CORNER_ENTER_G,
    CORNER_EXIT_G,
    CORNER_EXIT_WINDOW_S,
    CORNER_MERGE_GAP_S,
    CORNER_MIN_DURATION_S,
    CORNER_MIN_HEADING_DEG,
    CORNER_MIN_SPEED,
    END_OF_STRAIGHT_S,
    FULL_THROTTLE,
    LIMITER_MIN_RUN_S,
    LIMITER_RPM_PCT,
    SAMPLE_BUFFER_S,
    STRAIGHT_GAP_S,
    STRAIGHT_MIN_M,
)

Segment = CornerWindow | BrakeWindow | StraightRecord | BottomingEvent

_IDLE, _ACTIVE, _PENDING = 0, 1, 2
_MAX_FORWARD_GEAR = 10
_DEG = 57.29577951308232


class _StraightAcc:
    __slots__ = (
        "start_dist", "start_t", "cut_start", "gear", "gear_since", "lim_run", "lim_s",
        "max_gear", "last_t", "end_dist", "end_speed", "tail",
    )  # fmt: skip

    def __init__(self, s: Sample, cut_start: bool) -> None:
        self.start_dist = s.dist
        self.start_t = s.t
        self.cut_start = cut_start
        self.gear = s.gear
        self.gear_since = s.t
        self.lim_run = 0.0
        self.lim_s = 0.0
        self.max_gear = s.gear if 0 < s.gear <= _MAX_FORWARD_GEAR else 0
        self.last_t = s.t
        self.end_dist = s.dist
        self.end_speed = s.v
        self.tail: deque[tuple[float, float]] = deque()


class _BottomAcc:
    __slots__ = ("t", "dist", "speed", "last_t")

    def __init__(self, s: Sample) -> None:
        self.t = s.t
        self.dist = s.dist
        self.speed = s.v
        self.last_t = s.t


class Segmenter:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._buf: deque[Sample] = deque()
        self._first_i: int | None = None
        self._last: Sample | None = None
        # corner
        self._c_state = _IDLE
        self._c_sign = 0
        self._c_start = 0
        self._c_end = 0
        self._c_end_t = 0.0
        self._c_heading = 0.0
        self._c_gap_heading = 0.0
        self._prev_seg_end = -1
        # braking zone
        self._b_active = False
        self._b_start = 0
        self._b_start_t = 0.0
        self._b_last = 0
        self._b_last_t = 0.0
        # straight and bottoming
        self._st: _StraightAcc | None = None
        self._bot_f: _BottomAcc | None = None
        self._bot_r: _BottomAcc | None = None

    # -- public -------------------------------------------------------------------
    def push(self, s: Sample) -> list[Segment] | None:
        """Add one sample; return the segments completed by it (usually None)."""
        buf = self._buf
        if self._first_i is None:
            self._first_i = s.i
        buf.append(s)
        self._last = s
        while s.t - buf[0].t > SAMPLE_BUFFER_S:
            buf.popleft()

        out: list[Segment] | None = None
        seg = self._corner(s)
        if seg is not None:
            out = [seg]
        seg = self._brake(s)
        if seg is not None:
            out = [seg] if out is None else [*out, seg]
        seg = self._straight(s)
        if seg is not None:
            out = [seg] if out is None else [*out, seg]
        if s.v >= BOTTOMING_MIN_SPEED or self._bot_f is not None or self._bot_r is not None:
            for ev in self._bottoming(s):
                out = [ev] if out is None else [*out, ev]
        return out

    def flush(self) -> list[Segment]:
        """Close everything still open (end of a lap or of the data)."""
        out: list[Segment] = []
        last = self._last
        if last is None:
            return out
        if self._c_state != _IDLE:
            w = self._finish_corner(last.i, partial=self._c_state == _ACTIVE)
            if w is not None:
                out.append(w)
            self._c_state = _IDLE
        if self._b_active:
            w = self._finish_brake(partial=True)
            if w is not None:
                out.append(w)
        if self._st is not None:
            st = self._finish_straight(cut_end=True)
            if st is not None:
                out.append(st)
        for axle in ("front", "rear"):
            acc = self._bot_f if axle == "front" else self._bot_r
            if acc is not None:
                out.append(BottomingEvent(axle, acc.t, acc.dist, acc.speed, acc.last_t - acc.t))
        self._bot_f = self._bot_r = None
        return out

    # -- helpers ---------------------------------------------------------------------
    def _at(self, i: int) -> Sample:
        return self._buf[i - self._buf[0].i]

    def _slice(self, i0: int, i1: int) -> list[Sample]:
        base = self._buf[0].i
        return list(islice(self._buf, max(0, i0 - base), i1 - base + 1))

    # -- corners ---------------------------------------------------------------------
    def _corner(self, s: Sample) -> CornerWindow | None:
        lat = s.lat_g
        state = self._c_state
        if state == _ACTIVE:
            if lat * self._c_sign >= CORNER_EXIT_G:
                self._c_end = s.i
                self._c_end_t = s.t
                self._c_heading += abs(s.yaw) * s.dt
                return None
            self._c_state = _PENDING
            self._c_gap_heading = abs(s.yaw) * s.dt
            return None
        if state == _PENDING:
            gap = s.t - self._c_end_t
            if lat * self._c_sign >= CORNER_EXIT_G and gap <= CORNER_MERGE_GAP_S:
                self._c_heading += self._c_gap_heading + abs(s.yaw) * s.dt
                self._c_end = s.i
                self._c_end_t = s.t
                self._c_state = _ACTIVE
                return None
            if abs(lat) >= CORNER_ENTER_G and s.v >= CORNER_MIN_SPEED:
                sign = 1 if lat > 0 else -1
                start = self._backtrack(s, sign, self._c_end + 1)
                w = self._finish_corner(start - 1, partial=False)
                self._begin_corner(s, sign, start)
                return w
            self._c_gap_heading += abs(s.yaw) * s.dt
            if gap >= CORNER_EXIT_WINDOW_S:
                w = self._finish_corner(s.i, partial=False)
                self._c_state = _IDLE
                return w
            return None
        if abs(lat) >= CORNER_ENTER_G and s.v >= CORNER_MIN_SPEED:
            sign = 1 if lat > 0 else -1
            self._begin_corner(s, sign, self._backtrack(s, sign, self._prev_seg_end + 1))
        return None

    def _backtrack(self, s: Sample, sign: int, lower: int) -> int:
        lower = max(lower, self._buf[0].i)
        j = s.i
        while j - 1 >= lower and self._at(j - 1).lat_g * sign >= CORNER_EXIT_G:
            j -= 1
        return j

    def _begin_corner(self, s: Sample, sign: int, start: int) -> None:
        self._c_state = _ACTIVE
        self._c_sign = sign
        self._c_start = start
        self._c_end = s.i
        self._c_end_t = s.t
        heading = 0.0
        for k in range(start, s.i + 1):
            x = self._at(k)
            heading += abs(x.yaw) * x.dt
        self._c_heading = heading

    def _finish_corner(self, window_end: int, partial: bool) -> CornerWindow | None:
        start, end = self._c_start, self._c_end
        lower = max(self._prev_seg_end + 1, self._buf[0].i)
        self._prev_seg_end = end
        if start < self._buf[0].i:
            start = self._buf[0].i
            partial = True
        t0 = self._at(start).t
        if self._at(end).t - t0 < CORNER_MIN_DURATION_S:
            return None
        if self._c_heading * _DEG < CORNER_MIN_HEADING_DEG:
            return None
        partial = partial or start == self._first_i
        j = start
        while (
            j - 1 >= lower
            and self._at(j - 1).brk >= BRAKE_ON
            and t0 - self._at(j - 1).t <= BRAKE_LOOKBACK_S
        ):
            j -= 1
        samples = self._slice(j, max(window_end, end))
        return CornerWindow(samples, start - j, end - j, self._c_sign, partial)

    # -- braking zones ---------------------------------------------------------------
    def _brake(self, s: Sample) -> BrakeWindow | None:
        if s.brk >= BRAKE_ON:
            if not self._b_active:
                self._b_active = True
                self._b_start = s.i
                self._b_start_t = s.t
            self._b_last = s.i
            self._b_last_t = s.t
            return None
        if self._b_active and s.t - self._b_last_t > BRAKE_RELEASE_GAP_S:
            return self._finish_brake(partial=False)
        return None

    def _finish_brake(self, partial: bool) -> BrakeWindow | None:
        self._b_active = False
        if self._b_last_t - self._b_start_t < BRAKE_ZONE_MIN_S:
            return None
        partial = partial or self._b_start == self._first_i or self._b_start < self._buf[0].i
        return BrakeWindow(self._slice(self._b_start, self._b_last), partial)

    # -- straights ---------------------------------------------------------------------
    def _straight(self, s: Sample) -> StraightRecord | None:
        acc = self._st
        if s.thr >= FULL_THROTTLE:
            if acc is None:
                acc = self._st = _StraightAcc(s, cut_start=s.i == self._first_i)
            if s.gear != acc.gear:
                acc.gear = s.gear
                acc.gear_since = s.t
                acc.lim_run = 0.0
                acc.lim_s = 0.0
            if s.rpm_pct >= LIMITER_RPM_PCT:
                acc.lim_run += s.dt
            elif acc.lim_run:
                if acc.lim_run >= LIMITER_MIN_RUN_S:
                    acc.lim_s += acc.lim_run
                acc.lim_run = 0.0
            if acc.max_gear < s.gear <= _MAX_FORWARD_GEAR:
                acc.max_gear = s.gear
            acc.last_t = s.t
            acc.end_dist = s.dist
            acc.end_speed = s.v
            tail = acc.tail
            tail.append((s.t, s.rpm_pct))
            while tail[0][0] < s.t - END_OF_STRAIGHT_S:
                tail.popleft()
            return None
        if acc is not None and s.t - acc.last_t > STRAIGHT_GAP_S:
            return self._finish_straight(cut_end=False)
        return None

    def _finish_straight(self, cut_end: bool) -> StraightRecord | None:
        acc = self._st
        self._st = None
        if acc is None or acc.end_dist - acc.start_dist < STRAIGHT_MIN_M:
            return None
        if acc.lim_run >= LIMITER_MIN_RUN_S:
            acc.lim_s += acc.lim_run
        return StraightRecord(
            t_end=acc.last_t,
            start_dist=acc.start_dist,
            end_dist=acc.end_dist,
            duration=acc.last_t - acc.start_t,
            end_speed=acc.end_speed,
            end_gear=acc.gear,
            end_rpm_pct=max(r for _, r in acc.tail),
            gear_time_s=acc.last_t - acc.gear_since,
            limiter_s=acc.lim_s,
            max_gear=acc.max_gear,
            cut_start=acc.cut_start,
            cut_end=cut_end,
        )

    # -- bottoming ---------------------------------------------------------------------
    def _bottoming(self, s: Sample) -> list[BottomingEvent]:
        out: list[BottomingEvent] = []
        fast = s.v >= BOTTOMING_MIN_SPEED
        hit_f = fast and s.susp_f >= BOTTOMING_TRAVEL and not s.rumble_f
        hit_r = fast and s.susp_r >= BOTTOMING_TRAVEL and not s.rumble_r
        for axle, hit in (("front", hit_f), ("rear", hit_r)):
            acc = self._bot_f if axle == "front" else self._bot_r
            if hit:
                if acc is None:
                    acc = _BottomAcc(s)
                    if axle == "front":
                        self._bot_f = acc
                    else:
                        self._bot_r = acc
                acc.last_t = s.t
                if s.v > acc.speed:
                    acc.speed = s.v
            elif acc is not None and s.t - acc.last_t > BOTTOMING_MERGE_S:
                out.append(BottomingEvent(axle, acc.t, acc.dist, acc.speed, acc.last_t - acc.t))
                if axle == "front":
                    self._bot_f = None
                else:
                    self._bot_r = None
        return out
