"""Analysis adapters: per-lap / per-session engine and the live tuning board."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pitwall.services.engine import AnalysisUnavailable, LazyModule
from pitwall.services.live_analysis import LiveAnalysisService
from pitwall.telemetry.packet import blank_frame

from .conftest import AppFactory
from .helpers import fake_engine, fake_live, inject, synth_laps


def record(client: TestClient, laps: int = 2, **kwargs: Any) -> int:
    client.post("/api/recording/start")
    inject(client, synth_laps(laps, **kwargs))
    return client.post("/api/recording/stop").json()["id"]


def wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not met in time"
        time.sleep(0.005)


# --- per-lap / per-session -----------------------------------------------------


def test_analysis_unavailable(client: TestClient) -> None:
    session_id = record(client)
    lap_id = client.get(f"/api/sessions/{session_id}").json()["laps"][0]["id"]
    for path in (f"/api/laps/{lap_id}/analysis", f"/api/sessions/{session_id}/analysis"):
        response = client.get(path)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "analysis_unavailable"
    assert client.get(f"/api/laps/{lap_id}").json()["metrics"] is None


def test_lap_analysis_is_cached(app_factory: AppFactory) -> None:
    engine = fake_engine()
    client = app_factory(engine=engine)
    session_id = record(client)
    laps = client.get(f"/api/sessions/{session_id}").json()["laps"]
    services = client.app.state.services
    # Background analysis after each lap.
    wait_for(lambda: len(engine.calls["lap"]) >= len(laps))
    calls_before = len(engine.calls["lap"])

    result = client.get(f"/api/laps/{laps[0]['id']}/analysis").json()
    assert result == {"kind": "flying", "metrics": {"frames": 180}}
    assert client.get(f"/api/laps/{laps[0]['id']}").json()["metrics"] == {"frames": 180}
    assert len(engine.calls["lap"]) == calls_before  # served from cache

    ctx = engine.calls["lap"][0]
    assert ctx.drivetrain == "RWD" and ctx.lap_kind == "flying" and ctx.lap_valid is True
    assert ctx.unit_system == "metric" and ctx.lap_time == pytest.approx(3.0)
    assert ctx.tune_values == {}  # v1 tracks no tunes

    # A cold cache (e.g. after restart) recomputes from the raw packet file.
    services.frames.clear()
    services.analysis._objects.clear()
    services.store._execute("DELETE FROM analysis_cache")
    again = client.get(f"/api/laps/{laps[0]['id']}/analysis").json()
    assert again["metrics"]["frames"] == 180


def test_session_analysis(app_factory: AppFactory) -> None:
    engine = fake_engine()
    client = app_factory(engine=engine)
    record(client)
    second = record(client, laps=3)
    client.put("/api/settings", json={"units": {"speed": "mph"}})

    assert client.get(f"/api/sessions/{second}/analysis").json() == {"laps_analyzed": 4}
    ctx = engine.calls["session"][-1]
    assert ctx.drivetrain == "RWD" and ctx.unit_system == "imperial"
    # v1 tracks no tunes: nothing about tunes or the previous session is passed.
    assert ctx.tune_values == {} and ctx.previous_session is None and ctx.tune_changes == ()
    lap_ctx = engine.calls["lap"][-1]
    assert lap_ctx.unit_system == "imperial"  # unit change invalidated cached laps

    calls = len(engine.calls["session"])
    client.get(f"/api/sessions/{second}/analysis")
    assert len(engine.calls["session"]) == calls  # cached


# --- live tuning board: service ------------------------------------------------


def make_service(every: int = 30, **kwargs: Any) -> tuple[LiveAnalysisService, Any]:
    live = fake_live(every)
    service = LiveAnalysisService(
        lambda: "imperial",
        module=LazyModule("fake", loader=lambda name: live),
        **kwargs,
    )
    return service, live


def frames(n: int, car: int = 1234, track: int = 860, drivetrain: int = 1) -> list:
    return [
        blank_frame(
            is_race_on=True,
            recv_time=i / 60,
            car_ordinal=car,
            track_ordinal=track,
            drivetrain=drivetrain,
        )
        for i in range(n)
    ]


def test_live_service_unavailable() -> None:
    service = LiveAnalysisService(lambda: "metric", module=LazyModule("x", loader=_missing))
    service.start()
    assert not service.available
    service.on_frame(frames(1)[0])
    assert service.poll(0.0) is None
    with pytest.raises(AnalysisUnavailable):
        service.snapshot()
    with pytest.raises(AnalysisUnavailable):
        service.reset()


def _missing(name: str):
    raise ImportError(name)


def test_live_service_rate_limit_and_changes() -> None:
    service, live = make_service(every=30)
    service.start()
    try:
        assert service.poll(now=0.0)["corners_seen"] == 0  # initial snapshot
        service.on_frame(frames(1)[0])  # first frame: car seen -> reset
        assert service.poll(now=0.1) is None  # rate limited and unchanged
        for f in frames(30):
            service.on_frame(f)
        assert service.wait_idle()
        assert service.poll(now=0.2) is None  # changed, but < 0.5 s since last send
        assert service.poll(now=0.6)["corners_seen"] == 1
        assert service.poll(now=2.0) is None  # nothing new
        assert live.instances[-1].pushed == 31
    finally:
        service.stop()


def test_live_service_resets_on_car_or_track_change() -> None:
    service, live = make_service()
    service.start()
    try:
        assert len(live.instances) == 1
        for f in frames(5):
            service.on_frame(f)
        assert len(live.instances) == 2  # first car seen
        assert live.instances[-1].drivetrain == 1
        assert live.instances[-1].tune_values == {}
        assert live.instances[-1].unit_system == "imperial"
        for f in frames(5):
            service.on_frame(f)
        assert len(live.instances) == 2  # same car and track
        service.on_frame(frames(1, track=999)[0])
        assert len(live.instances) == 3
        service.on_frame(frames(1, car=42, track=999, drivetrain=2)[0])
        assert len(live.instances) == 4 and live.instances[-1].drivetrain == 2
        service.reset()
        assert len(live.instances) == 5
        # Race-off frames are ignored.
        service.on_frame(blank_frame(car_ordinal=1))
        assert len(live.instances) == 5
    finally:
        service.stop()


def test_live_service_drops_frames_when_busy() -> None:
    gate = threading.Event()
    service, live = make_service(queue_size=10)
    service.start()
    try:
        service.on_frame(frames(1)[0])
        analyzer = live.instances[-1]
        original = analyzer.push

        def slow_push(frame):
            gate.wait(2.0)
            return original(frame)

        analyzer.push = slow_push
        start = time.perf_counter()
        for f in frames(100):
            service.on_frame(f)
        assert time.perf_counter() - start < 0.5  # never blocks the caller
        assert service.dropped_frames >= 80
        gate.set()
        assert service.wait_idle()
    finally:
        gate.set()
        service.stop()


def test_live_service_discards_frames_queued_before_reset() -> None:
    gate = threading.Event()
    service, live = make_service()
    service.start()
    try:
        service.on_frame(frames(1)[0])
        old = live.instances[-1]
        original = old.push
        old.push = lambda f: (gate.wait(2.0), original(f))[1]
        for f in frames(20):
            service.on_frame(f)
        service.reset()
        gate.set()
        assert service.wait_idle()
        assert old.pushed <= 2
        assert live.instances[-1].pushed == 0
    finally:
        gate.set()
        service.stop()


# --- live tuning board: API and WebSocket -------------------------------------


def test_live_api_unavailable(client: TestClient) -> None:
    for response in (client.get("/api/live-analysis"), client.post("/api/live-analysis/reset")):
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "analysis_unavailable"
    with client.websocket_connect("/ws/live") as ws:
        assert ws.receive_json()["type"] == "status"
        inject(client, synth_laps(0, tail_s=0.5))
        while (message := ws.receive_json())["type"] != "telemetry":
            assert message["type"] != "live_analysis"


def test_live_api_and_ws(app_factory: AppFactory) -> None:
    live = fake_live(every=30)
    client = app_factory(live=live)
    snapshot = client.get("/api/live-analysis").json()
    assert snapshot == {
        "corners_seen": 0,
        "window": {"corners": 12, "laps": 0.0},
        "focus": None,
        "items": [],
    }
    with client.websocket_connect("/ws/live") as ws:
        assert ws.receive_json()["type"] == "status"
        on_connect = ws.receive_json()
        assert on_connect["type"] == "live_analysis" and on_connect["corners_seen"] == 0

        inject(client, synth_laps(0, tail_s=1.0))  # 60 frames -> 2 snapshots
        client.app.state.services.live_analysis.wait_idle()
        for _ in range(200):
            message = ws.receive_json()
            if message["type"] == "live_analysis" and message["corners_seen"] == 2:
                break
        else:
            raise AssertionError("no updated live_analysis message")

    reset = client.post("/api/live-analysis/reset").json()
    assert reset["corners_seen"] == 0
    assert client.get("/api/live-analysis").json()["corners_seen"] == 0


def test_live_reset_via_api_rebuilds_the_analyzer(app_factory: AppFactory) -> None:
    live = fake_live()
    client = app_factory(live=live)
    client.put("/api/settings", json={"units": {"speed": "mph"}})
    inject(client, synth_laps(0, tail_s=0.5))
    count = len(live.instances)
    client.post("/api/live-analysis/reset")
    assert len(live.instances) == count + 1
    assert live.instances[-1].drivetrain == 1 and live.instances[-1].unit_system == "imperial"
    assert live.instances[-1].tune_values == {}
