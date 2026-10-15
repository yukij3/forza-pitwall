from __future__ import annotations

from dataclasses import replace

import pytest

from pitwall.telemetry.laps import LapSegment, LapSegmenter
from pitwall.telemetry.model import Frame

from .helpers import synth_laps


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
    # Last frame before the line shows current_lap one frame short of the lap time.
    assert laps[0].lap_time == pytest.approx(3.0 - 1 / 60)


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
    assert summary(laps)[:4] == [
        (1, "flying", True, None),  # the lap that crossed the line first
        (2, "partial", False, "rewind"),  # 0.5 s of lap 2, undone by the rewind
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


def test_trailing_lap_ended_by_race_off_is_an_in_lap() -> None:
    frames = synth_laps(1)
    seg = LapSegmenter()
    out: list[LapSegment] = []
    for i, f in enumerate(frames):
        out += seg.add(f, i)
    seg.note_race_off()
    out += seg.finish()
    assert summary(out) == [(1, "flying", True, None), (2, "in", True, None)]


def test_short_trailing_segment_is_dropped() -> None:
    laps = run(synth_laps(1, tail_s=0.5))
    assert summary(laps) == [(1, "flying", True, None)]
