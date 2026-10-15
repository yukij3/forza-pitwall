from __future__ import annotations

from dataclasses import replace

import pytest

from pitwall.telemetry.laps import LapSegment, LapSegmenter
from pitwall.telemetry.model import Frame

from .helpers import Rewind, race_session, segment, synth_laps


def run(frames: list[Frame], *, race_off_at: dict[int, int] | None = None) -> list[LapSegment]:
    """Feed frames; ``race_off_at`` maps frame index -> race-off packets before it."""
    seg = LapSegmenter(wall_clock=lambda: 1000.0)
    out: list[LapSegment] = []
    for i, frame in enumerate(frames):
        for _ in range((race_off_at or {}).get(i, 0)):
            seg.note_race_off()
        out += seg.add(frame, i)
    return out + seg.finish()


def summary(laps: list[LapSegment]) -> list[tuple[int, str, bool, str | None]]:
    return [(lap.number, lap.kind, lap.valid, lap.invalid_reason) for lap in laps]


def test_clean_laps_from_standing_start() -> None:
    laps = run(synth_laps(3, standing_start=True))
    assert summary(laps) == [
        (1, "out", True, None),
        (2, "flying", True, None),
        (3, "flying", True, None),
        (4, "partial", False, "partial"),
    ]
    assert [lap.lap_time for lap in laps[:3]] == pytest.approx([3.0, 3.01, 3.02])
    assert laps[3].lap_time is None


def test_frame_indices_cover_the_stream() -> None:
    frames = synth_laps(2)
    laps = run(frames)
    assert laps[0].first_index == 0
    for a, b in zip(laps, laps[1:], strict=False):
        assert b.first_index == a.first_index + a.frame_count
    assert sum(lap.frame_count for lap in laps) == len(frames)


@pytest.mark.parametrize("lag", [0, 1, 5])
def test_lap_time_waits_for_last_lap_update(lag: int) -> None:
    laps = run(synth_laps(3, last_lap_lag=lag))
    assert [lap.lap_time for lap in laps[:3]] == pytest.approx([3.0, 3.01, 3.02])


def test_lap_time_falls_back_to_current_lap() -> None:
    frames = [replace(f, last_lap=0.0) for f in synth_laps(2)]
    laps = run(frames)
    # The last frame before the line shows the lap timer just short of the lap time.
    assert laps[0].lap_time == pytest.approx(3.0 - 0.75 / 60)


def test_recording_started_mid_lap_is_partial() -> None:
    laps = run(synth_laps(2, start_offset_s=1.5))
    assert summary(laps)[:2] == [(1, "partial", False, "partial"), (2, "flying", True, None)]


def test_rewind_within_a_lap() -> None:
    frames = synth_laps(3)
    lap2 = [i for i, f in enumerate(frames) if f.lap_number == 1]
    cut = lap2[100]
    # Jump back 1 s in time and distance, as a rewind does.
    rewound = frames[: cut + 1] + frames[cut - 60 : cut - 59] + frames[cut + 1 :]
    laps = run(rewound)
    assert summary(laps)[:3] == [
        (1, "flying", True, None),
        (2, "flying", False, "rewind"),
        (3, "flying", True, None),
    ]


def test_rewind_across_the_line() -> None:
    frames = synth_laps(3)
    first_of_lap2 = next(i for i, f in enumerate(frames) if f.lap_number == 1)
    # 0.5 s into lap 2, rewind to 1 s before the line (back in lap 1).
    back = frames[first_of_lap2 - 60 : first_of_lap2]
    rewound = frames[: first_of_lap2 + 30] + back + frames[first_of_lap2:]
    laps = run(rewound)
    assert summary(laps)[:3] == [
        (1, "flying", True, None),  # the lap that crossed the line first
        # (0.5 s of lap 2, undone by the rewind, is too short to keep)
        (1, "partial", False, "partial"),  # re-driven end of lap 1
        (2, "flying", True, None),
    ]


def test_pause_mid_lap_invalidates() -> None:
    frames = synth_laps(3)
    mid_lap2 = next(i for i, f in enumerate(frames) if f.lap_number == 1) + 90
    laps = run(frames, race_off_at={mid_lap2: 20})
    assert summary(laps)[:3] == [
        (1, "flying", True, None),
        (2, "flying", False, "pause"),
        (3, "flying", True, None),
    ]


def test_data_gap_invalidates() -> None:
    frames = synth_laps(2)
    mid = next(i for i, f in enumerate(frames) if f.lap_number == 1) + 60
    frames = frames[:mid] + [replace(f, recv_time=f.recv_time + 2.0) for f in frames[mid:]]
    laps = run(frames)
    assert summary(laps)[1] == (2, "flying", False, "data_gap")


def test_trailing_lap_ended_by_race_off_at_speed_is_partial() -> None:
    frames = synth_laps(1)
    seg = LapSegmenter()
    out: list[LapSegment] = []
    for i, f in enumerate(frames):
        out += seg.add(f, i)
    seg.note_race_off()
    out += seg.finish()
    assert summary(out) == [(1, "flying", True, None), (2, "partial", False, "partial")]
    assert out[1].ended_by_race_off


def test_trailing_lap_ending_stopped_is_an_in_lap() -> None:
    frames = synth_laps(1)
    tail = [f for f in frames if f.lap_number == 1]
    stopped = frames[: -len(tail)] + [replace(f, speed=0.0) for f in tail[-80:]]
    assert summary(run(stopped))[-1] == (2, "in", True, None)


def test_short_trailing_segment_is_dropped() -> None:
    laps = run(synth_laps(1, tail_s=0.5))
    assert summary(laps) == [(1, "flying", True, None)]


# --- patterns from real Forza Motorsport (2023) recordings -------------------------
# Built synthetically (see helpers.race_session); no recorded data in the repo.


def test_race_start_and_finish() -> None:
    """Grid start behind the line, two laps, race-off at the chequered flag."""
    laps = segment(race_session(laps=2))
    assert summary(laps) == [(1, "flying", True, None), (2, "flying", True, None)]
    assert laps[0].lap_time == pytest.approx(10.0, abs=0.01)  # LastLap
    assert laps[1].lap_time == pytest.approx(10.0, abs=0.02)  # lap timer at the flag
    assert laps[1].ended_by_race_off and laps[1].ended_at_line
    # Neither the pre-race grid nor the run-up to the line is part of a lap.
    assert laps[0].frames[0].current_lap < 0.05
    assert laps[0].frames[0].distance_traveled >= 0


def test_pre_race_and_run_up_frames_are_skipped() -> None:
    frames = race_session(laps=1, end="finish")
    laps = segment(frames)
    first_lap_index = next(
        i for i, (a, b) in enumerate(zip(frames, frames[1:], strict=False), 1)
        if a.current_lap > 1 and b.current_lap < 0.05
    )  # fmt: skip
    assert laps[0].first_index == first_lap_index


def test_rewind_with_race_off_screen_is_a_rewind_not_a_pause() -> None:
    laps = segment(
        race_session(laps=2, rewinds=[Rewind(lap=0, at_s=6.0, back_s=3.0), Rewind(1, 4.0, 2.0)])
    )
    assert summary(laps) == [(1, "flying", False, "rewind"), (2, "flying", False, "rewind")]
    assert laps[0].lap_time == pytest.approx(10.0, abs=0.01)
    assert laps[1].lap_time == pytest.approx(10.0, abs=0.02)  # finish still detected


def test_pause_without_going_back_is_a_pause() -> None:
    frames = race_session(laps=2)
    mid = next(i for i, f in enumerate(frames) if f.lap_number == 0 and f.distance_traveled > 200)
    off = [replace(frames[mid], is_race_on=False)] * 50
    resumed = [replace(f, recv_time=f.recv_time + 3.0) for f in frames[mid:]]
    laps = segment(frames[:mid] + off + resumed)
    assert summary(laps)[0] == (1, "flying", False, "pause")


def test_quitting_mid_lap_is_partial_not_pause() -> None:
    laps = segment(race_session(laps=2, end="quit", quit_at_m=150.0))
    assert summary(laps) == [(1, "flying", True, None), (2, "partial", False, "partial")]
    assert laps[1].lap_time is None and laps[1].ended_by_race_off


def test_one_lap_race_finish_uses_the_grid_distance() -> None:
    laps = segment(race_session(laps=1, lap_m=600.0))
    assert summary(laps) == [(1, "flying", True, None)]
    assert laps[0].lap_time == pytest.approx(15.0, abs=0.02)


def test_race_restart_abandons_the_lap_without_calling_it_a_rewind() -> None:
    first = race_session(laps=2, end="quit", quit_at_m=200.0)
    again = race_session(laps=1, t0=first[-1].recv_time + 5.0)
    laps = segment(first + again)
    assert summary(laps) == [
        (1, "flying", True, None),
        (2, "partial", False, "partial"),
        (1, "flying", True, None),
    ]


@pytest.mark.parametrize("hz", [60.0, 125.0, 160.0])
def test_packet_rate_does_not_matter(hz: float) -> None:
    laps = segment(race_session(laps=3, hz=hz))
    assert [lap.kind for lap in laps] == ["flying"] * 3
    assert all(lap.valid for lap in laps)
    assert [round(lap.lap_time, 1) for lap in laps] == [10.0, 10.0, 10.0]


def test_last_lap_lag_is_measured_in_time_not_frames() -> None:
    # 160 packets/s and LastLap updating 0.2 s (32 packets) after the line.
    frames = race_session(laps=3, hz=160.0)
    lagged, hold, old = [], 0, 0.0
    for prev, f in zip([frames[0], *frames], frames, strict=False):
        if f.is_race_on and prev.is_race_on and f.lap_number > prev.lap_number:
            hold, old = 32, prev.last_lap
        if hold and f.is_race_on:
            hold -= 1
            f = replace(f, last_lap=old)
        lagged.append(f)
    laps = segment(lagged)
    assert [round(lap.lap_time, 2) for lap in laps] == [10.0, 10.0, 10.0]
