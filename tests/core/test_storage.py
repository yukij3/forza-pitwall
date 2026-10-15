from __future__ import annotations

from pathlib import Path

import pytest

from pitwall.services.recorder import AUTO_STOP_S, Recorder, RecordingError
from pitwall.storage.db import Store
from pitwall.storage.rawlog import MAGIC, RawLogError, RawWriter, iter_records, read_records
from pitwall.telemetry.packet import encode, parse

from .helpers import race_off, synth_laps


def test_raw_round_trip_and_slicing(tmp_path: Path) -> None:
    path = tmp_path / "s.pitwall"
    writer = RawWriter(path)
    for i in range(500):
        assert writer.append(i * 0.5, bytes([i % 256]) * (i % 7 + 1)) == i
    writer.close()
    records = read_records(path)
    assert len(records) == 500
    assert records[10] == (5.0, bytes([10]) * 4)
    assert read_records(path, 100, 3) == records[100:103]
    assert read_records(path, 498, 10) == records[498:]


def test_raw_truncated_file_is_readable(tmp_path: Path) -> None:
    path = tmp_path / "s.pitwall"
    writer = RawWriter(path)
    for i in range(1000):
        writer.append(float(i), b"x" * 331)
    writer.flush()
    size = path.stat().st_size
    # Simulate a crash: copy what's on disk now, without the gzip trailer.
    crashed = tmp_path / "crashed.pitwall"
    crashed.write_bytes(path.read_bytes()[: size - 3])
    writer.close()
    records = list(iter_records(crashed))
    assert 900 <= len(records) <= 1000
    assert all(len(p) == 331 for _, p in records)


def test_raw_bad_magic(tmp_path: Path) -> None:
    import gzip

    path = tmp_path / "bad.pitwall"
    with gzip.open(path, "wb") as fh:
        fh.write(b"NOTMAGIC" + bytes(20))
    with pytest.raises(RawLogError):
        read_records(path)
    assert MAGIC != b"NOTMAGIC"


def make_recorder(tmp_path: Path) -> tuple[Store, Recorder, list[dict]]:
    store = Store(tmp_path / "data")
    laps: list[dict] = []
    recorder = Recorder(store, on_lap=lambda s, lap, frames: laps.append(lap))
    return store, recorder, laps


def feed(recorder: Recorder, frames) -> None:
    for f in frames:
        recorder.handle_frame(f, encode(f))


def test_recorder_start_stop_errors(tmp_path: Path) -> None:
    _, recorder, _ = make_recorder(tmp_path)
    with pytest.raises(RecordingError) as err:
        recorder.stop()
    assert err.value.code == "not_recording"
    recorder.start()
    with pytest.raises(RecordingError) as err:
        recorder.start()
    assert err.value.code == "already_recording"


def test_recorder_stores_laps_and_raw_packets(tmp_path: Path) -> None:
    store, recorder, laps_cb = make_recorder(tmp_path)
    frames = synth_laps(2, t0=100.0)
    recorder.start("test")
    feed(recorder, frames[:200])
    feed(recorder, race_off(30, frames[199].recv_time + 0.01))  # not recorded
    feed(recorder, frames[200:])
    session = recorder.stop()

    assert session["car_ordinal"] == 1234 and session["drivetrain"] == "RWD"
    assert session["track_ordinal"] == 860 and session["stopped_at"]
    assert session["frame_count"] == len(frames)
    laps = store.list_laps(session["id"])
    assert [(lap["number"], lap["kind"], lap["valid"]) for lap in laps] == [
        (1, "flying", True),
        (2, "flying", False),  # race-off frames mid-lap = pause
        (3, "partial", False),
    ]
    assert len(laps_cb) == 3
    assert session["best_lap"] == pytest.approx(3.0)
    assert session["lap_count"] == 3

    raw = read_records(store.raw_path(session))
    assert len(raw) == len(frames)
    lap2 = laps[1]
    first = parse(raw[lap2["first_frame"]][1], 0.0)
    assert first.lap_number == 1 and first.current_lap == 0.0


def test_auto_record_starts_and_stops(tmp_path: Path) -> None:
    store, recorder, _ = make_recorder(tmp_path)
    recorder.set_auto_record(True)
    frames = synth_laps(1, t0=10.0)
    feed(recorder, race_off(10, 9.0))
    assert not recorder.active
    feed(recorder, frames)
    assert recorder.active
    session_id = recorder.session_id
    end = frames[-1].recv_time
    feed(recorder, race_off(5, end + 1.0))
    assert recorder.active
    feed(recorder, race_off(1, end + AUTO_STOP_S + 0.1))
    assert not recorder.active
    assert store.get_session(session_id)["note"] == "Auto-recorded"


def test_auto_stop_on_silence_but_not_for_manual_sessions(tmp_path: Path) -> None:
    _, recorder, _ = make_recorder(tmp_path)
    recorder.set_auto_record(True)
    frames = synth_laps(1, t0=10.0)
    feed(recorder, frames)
    assert recorder.active
    recorder.tick(now=frames[-1].recv_time + AUTO_STOP_S + 1)
    assert not recorder.active

    recorder.set_auto_record(False)
    recorder.start("manual")
    recorder.tick(now=1e9)
    assert recorder.active


def test_dangling_sessions_are_closed(tmp_path: Path) -> None:
    store = Store(tmp_path / "data")
    session = store.create_session(started_at="2026-01-01T00:00:00.000Z", note="")
    store.close()
    store = Store(tmp_path / "data")
    assert store.close_dangling_sessions("2026-01-01T01:00:00.000Z") == 1
    assert store.get_session(session["id"])["stopped_at"] == "2026-01-01T01:00:00.000Z"
