from __future__ import annotations

import gzip
import sqlite3
import struct
from pathlib import Path

import pytest

from pitwall.__main__ import main
from pitwall.services.frames import LapFrames
from pitwall.services.recorder import AUTO_STOP_S, Recorder, RecordingError
from pitwall.storage.db import Store
from pitwall.storage.rawlog import (
    MAGIC,
    MAGIC_V1,
    RawLogError,
    RawWriter,
    iter_records,
    raw_version,
    read_records,
)
from pitwall.telemetry.packet import encode, parse
from pitwall.tools.reindex import reindex

from .helpers import Rewind, race_off, race_session, synth_laps


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
    feed(recorder, race_off(30, frames[199].recv_time + 0.01))  # one kept as a marker
    feed(recorder, frames[200:])
    session = recorder.stop()

    assert session["car_ordinal"] == 1234 and session["drivetrain"] == "RWD"
    assert session["track_ordinal"] == 860 and session["stopped_at"]
    assert session["frame_count"] == len(frames) + 1
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
    assert len(raw) == len(frames) + 1
    assert not parse(raw[200][1], 0.0).is_race_on  # the race-off marker
    lap2 = laps[1]
    first = parse(raw[lap2["first_frame"]][1], 0.0)
    assert first.lap_number == 1 and first.current_lap < 0.01
    # The lap's frames come back without the marker.
    assert len(LapFrames(store).get(lap2)) == lap2["frame_count"]
    assert lap2["last_frame"] - lap2["first_frame"] + 1 == lap2["frame_count"] + 1


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


def test_race_finish_is_stored_when_the_game_leaves_the_race(tmp_path: Path) -> None:
    """The last lap of a race is complete as soon as race-off arrives at the line."""
    store, recorder, laps_cb = make_recorder(tmp_path)
    recorder.start()
    feed(recorder, race_session(laps=2))
    assert [(lap["kind"], lap["valid"]) for lap in laps_cb] == [("flying", True)] * 2
    assert laps_cb[1]["lap_time"] == pytest.approx(10.0, abs=0.02)
    session = recorder.stop()
    assert session["lap_count"] == 2 and session["best_lap"] == pytest.approx(10.0, abs=0.02)


def test_schema_1_database_is_migrated(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    db = sqlite3.connect(data / "pitwall.db")
    db.executescript(
        """
        CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL,
            stopped_at TEXT, car_ordinal INTEGER, car_pi INTEGER, car_class INTEGER,
            drivetrain TEXT, track_ordinal INTEGER, note TEXT NOT NULL DEFAULT '',
            raw_file TEXT, frame_count INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE laps (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL,
            number INTEGER NOT NULL, lap_time REAL, kind TEXT NOT NULL, valid INTEGER NOT NULL,
            invalid_reason TEXT, frame_count INTEGER NOT NULL, first_frame INTEGER NOT NULL,
            started_at TEXT NOT NULL);
        INSERT INTO sessions (started_at) VALUES ('2026-01-01T00:00:00.000Z');
        INSERT INTO laps (session_id, number, kind, valid, frame_count, first_frame, started_at)
            VALUES (1, 1, 'flying', 1, 100, 20, '2026-01-01T00:00:00.000Z');
        PRAGMA user_version = 1;
        """
    )
    db.close()
    store = Store(data)
    assert store.list_laps(1)[0]["last_frame"] == 119
    store.close()


def record_race(tmp_path: Path, frames) -> tuple[Store, dict]:
    store, recorder, _ = make_recorder(tmp_path)
    recorder.start()
    feed(recorder, frames)
    return store, recorder.stop()


LAP_KEYS = ("number", "kind", "valid", "invalid_reason", "lap_time", "first_frame", "last_frame")


def test_reindex_reproduces_live_segmentation(tmp_path: Path) -> None:
    frames = race_session(laps=3, rewinds=[Rewind(lap=1, at_s=5.0, back_s=2.0)])
    store, session = record_race(tmp_path, frames)
    live = [{k: lap[k] for k in LAP_KEYS} for lap in store.list_laps(session["id"])]
    [result] = reindex(store, analyze=False)
    again = [{k: lap[k] for k in LAP_KEYS} for lap in store.list_laps(session["id"])]
    assert again == live
    assert [lap["invalid_reason"] for lap in again] == [None, "rewind", None]
    assert result.before != [] and result.skipped is None


def write_v1(path: Path, frames) -> None:
    """A raw file as older versions wrote it: race-on packets only."""
    with gzip.open(path, "wb") as fh:
        fh.write(MAGIC_V1)
        for f in frames:
            if f.is_race_on:
                payload = encode(f)
                fh.write(struct.pack("<dH", f.recv_time, len(payload)) + payload)


def test_reindex_old_file_reads_gaps_as_race_off(tmp_path: Path) -> None:
    store = Store(tmp_path / "data")
    session = store.create_session(started_at="2026-01-01T00:00:00.000Z", note="")
    store.stop_session(session["id"], stopped_at="2026-01-01T00:05:00.000Z", frame_count=0)
    frames = race_session(laps=2, rewinds=[Rewind(lap=0, at_s=6.0, back_s=3.0)])
    write_v1(store.raw_path(session), frames)
    assert raw_version(store.raw_path(session)) == 1

    preview = reindex(store, dry_run=True)
    assert store.list_laps(session["id"]) == []  # dry run wrote nothing
    assert [lap["kind"] for lap in preview[0].after] == ["flying", "flying"]

    reindex(store, analyze=False)
    laps = store.list_laps(session["id"])
    assert [(lap["kind"], lap["invalid_reason"]) for lap in laps] == [
        ("flying", "rewind"),
        ("flying", None),
    ]
    assert laps[1]["lap_time"] == pytest.approx(10.0, abs=0.02)
    assert laps[0]["started_at"].startswith("2026-01-01T00:00:0")


def test_reindex_skips_open_and_missing_sessions(tmp_path: Path) -> None:
    store = Store(tmp_path / "data")
    store.create_session(started_at="2026-01-01T00:00:00.000Z", note="")
    gone = store.create_session(started_at="2026-01-01T00:00:00.000Z", note="")
    store.stop_session(gone["id"], stopped_at="2026-01-01T00:01:00.000Z", frame_count=0)
    results = {r.session_id: r.skipped for r in reindex(store, analyze=False)}
    assert results == {1: "still recording", 2: "raw packet file missing"}


def test_reindex_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store, session = record_race(tmp_path, race_session(laps=2))
    store.close()
    assert main(["reindex", "--data-dir", str(tmp_path / "data"), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert f"session {session['id']}" in out and "flying" in out and "dry run" in out
