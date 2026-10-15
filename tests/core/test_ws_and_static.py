from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from .conftest import AppFactory
from .helpers import fake_engine, inject, synth_laps


def receive_until(ws: Any, msg_type: str, limit: int = 200) -> dict[str, Any]:
    for _ in range(limit):
        message = ws.receive_json()
        if message["type"] == msg_type:
            return message
    raise AssertionError(f"no {msg_type!r} message")


def test_ws_status_on_connect_and_telemetry(client: TestClient) -> None:
    with client.websocket_connect("/ws/live") as ws:
        first = ws.receive_json()
        assert first["type"] == "status"
        assert {"receiver", "recording", "car", "track_ordinal", "active_tune_id"} <= set(first)

        inject(client, synth_laps(0, tail_s=0.5))
        tele = receive_until(ws, "telemetry")
        assert set(tele) == {
            "type", "t", "speed", "rpm", "max_rpm", "gear", "throttle", "brake", "steer",
            "lap_number", "current_lap", "last_lap", "best_lap", "race_position",
            "lat_g", "lon_g", "tire_temp", "tire_wear", "slip_angle", "slip_ratio",
            "susp", "pos",
        }  # fmt: skip
        assert tele["speed"] == 50.0 and tele["gear"] == 4 and tele["lap_number"] == 1
        assert tele["throttle"] == 1.0 and tele["brake"] == 0.0 and tele["steer"] == -1.0
        assert tele["tire_temp"] == {"fl": 100.0, "fr": 100.0, "rl": 80.0, "rr": 80.0}
        assert tele["tire_wear"]["rl"] == 0.5 and tele["susp"]["fl"] == 0.5
        assert tele["lat_g"] == pytest.approx(1.0) and tele["lon_g"] == pytest.approx(-0.5)
        assert tele["last_lap"] is None and tele["max_rpm"] == 9000.0
        assert set(tele["pos"]) == {"x", "z"}


def test_ws_lap_completed(client: TestClient) -> None:
    client.post("/api/recording/start")
    with client.websocket_connect("/ws/live") as ws:
        ws.receive_json()
        inject(client, synth_laps(1, tail_s=1.0))
        message = receive_until(ws, "lap_completed")
        session_id = client.get("/api/status").json()["recording"]["session_id"]
        assert message["session_id"] == session_id
        assert message["lap"]["number"] == 1 and message["lap"]["kind"] == "flying"
        assert message["lap"]["lap_time"] == pytest.approx(3.0)
        # Status follows the lap count.
        status = receive_until(ws, "status")
        assert status["recording"]["active"] is True


def test_ws_analysis_ready(app_factory: AppFactory) -> None:
    client = app_factory(engine=fake_engine())
    client.post("/api/recording/start")
    with client.websocket_connect("/ws/live") as ws:
        ws.receive_json()
        inject(client, synth_laps(1, tail_s=1.0))
        ready = receive_until(ws, "analysis_ready")
        lap_id = client.get(f"/api/sessions/{ready['session_id']}").json()["laps"][0]["id"]
        assert ready["lap_id"] == lap_id


def test_static_ui_does_not_shadow_api(app_factory: AppFactory, tmp_path: Path) -> None:
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>UI</title>")
    (web / "app.js").write_text("export const ok = true;")
    client = app_factory(web_dir=web)

    root = client.get("/")
    assert root.status_code == 200 and "<title>UI</title>" in root.text
    assert client.get("/app.js").text.startswith("export")
    assert client.get("/api/status").json()["receiver"]["udp_port"] == 0
    missing = client.get("/api/missing")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    assert client.get("/missing.css").status_code == 404
    with client.websocket_connect("/ws/live") as ws:
        assert ws.receive_json()["type"] == "status"


def test_placeholder_without_web_dir(client: TestClient) -> None:
    root = client.get("/")
    assert root.status_code == 200 and "Pitwall" in root.text
    assert client.get("/api/docs").status_code == 200
