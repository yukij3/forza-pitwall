from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pitwall.app import create_app
from pitwall.config import Config
from pitwall.storage.db import Store
from pitwall.tune.settings import SETTINGS

from .conftest import AppFactory
from .helpers import fake_baselines, inject, race_off, synth_laps


def error_code(response) -> str:
    body = response.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message"}
    return body["error"]["code"]


def test_status_shape(client: TestClient) -> None:
    status = client.get("/api/status").json()
    assert set(status) == {"receiver", "recording", "car", "track_ordinal"}
    receiver = status["receiver"]
    assert receiver["listening"] is False  # UDP not bound in tests
    assert receiver["packets_per_sec"] == 0 and receiver["last_packet_age_s"] is None
    assert status["recording"] == {
        "active": False,
        "session_id": None,
        "started_at": None,
        "laps": 0,
    }
    assert status["car"] is None and status["track_ordinal"] is None


def test_status_reflects_packets(client: TestClient) -> None:
    inject(client, synth_laps(0, tail_s=1.0))
    status = client.get("/api/status").json()
    assert status["car"] == {
        "ordinal": 1234,
        "name": None,  # baselines module not installed
        "division": None,
        "class": 6,
        "class_name": "R",
        "pi": 812,
        "drivetrain": "RWD",
    }
    assert status["track_ordinal"] == 860
    assert status["receiver"]["race_on"] is True


def test_status_keeps_car_in_menus(client: TestClient) -> None:
    frames = synth_laps(0, tail_s=0.5)
    inject(client, frames + race_off(30, frames[-1].recv_time + 0.02))
    status = client.get("/api/status").json()
    assert status["car"]["ordinal"] == 1234 and status["track_ordinal"] == 860
    assert status["receiver"]["race_on"] is False


def test_ignored_packets_are_counted(client: TestClient) -> None:
    receiver = client.app.state.services.receiver
    client.portal.call(receiver.handle_packet, bytes(232))
    status = client.get("/api/status").json()
    assert status["receiver"]["ignored_packets"] == 1
    assert status["receiver"]["last_ignored_size"] == 232


def record_session(client: TestClient, laps: int = 2, note: str = "stint") -> dict:
    started = client.post("/api/recording/start", json={"note": note})
    assert started.status_code == 200
    inject(client, synth_laps(laps))
    stopped = client.post("/api/recording/stop")
    assert stopped.status_code == 200
    return stopped.json()


def test_recording_flow(client: TestClient) -> None:
    assert error_code(client.post("/api/recording/stop")) == "not_recording"
    started = client.post("/api/recording/start").json()
    assert started["recording"] is True and started["stopped_at"] is None
    conflict = client.post("/api/recording/start", json={})
    assert conflict.status_code == 409 and error_code(conflict) == "already_recording"

    inject(client, synth_laps(2))
    status = client.get("/api/status").json()["recording"]
    assert status["active"] and status["session_id"] == started["id"] and status["laps"] == 2

    stopped = client.post("/api/recording/stop").json()
    assert stopped["id"] == started["id"] and stopped["stopped_at"]
    assert stopped["lap_count"] == 3 and stopped["best_lap"] == pytest.approx(3.0)
    assert stopped["car_ordinal"] == 1234 and stopped["car_class_name"] == "R"
    assert "raw_file" not in stopped


def test_sessions_and_laps(client: TestClient) -> None:
    first = record_session(client, note="first")
    second = record_session(client, laps=1, note="second")
    sessions = client.get("/api/sessions").json()
    assert [s["id"] for s in sessions] == [second["id"], first["id"]]
    assert sessions[0]["lap_count"] == 2 and sessions[0]["note"] == "second"

    detail = client.get(f"/api/sessions/{first['id']}").json()
    assert [lap["kind"] for lap in detail["laps"]] == ["flying", "flying", "partial"]
    lap = detail["laps"][0]
    assert set(lap) == {
        "id", "session_id", "number", "lap_time", "kind", "valid",
        "invalid_reason", "frame_count", "started_at",
    }  # fmt: skip

    lap_detail = client.get(f"/api/laps/{lap['id']}").json()
    assert lap_detail["metrics"] is None  # no analysis engine
    assert lap_detail["frame_count"] == 180

    assert error_code(client.get("/api/sessions/999")) == "not_found"
    assert error_code(client.get("/api/laps/999")) == "not_found"


def test_trace(client: TestClient) -> None:
    session = record_session(client)
    lap = client.get(f"/api/sessions/{session['id']}").json()["laps"][1]
    trace = client.get(f"/api/laps/{lap['id']}/trace", params={"hz": 10}).json()
    keys = {
        "hz", "t", "distance", "speed", "throttle", "brake", "steer", "gear", "rpm",
        "lat_g", "lon_g", "slip_angle_front", "slip_angle_rear", "slip_ratio_rear",
        "susp_front", "susp_rear", "pos_x", "pos_z",
    }  # fmt: skip
    assert set(trace) == keys
    n = len(trace["t"])
    assert n == 30  # 180 frames = 2.983 s of lap at 10 Hz
    assert all(len(trace[k]) == n for k in keys - {"hz"})
    assert trace["t"][1] - trace["t"][0] == pytest.approx(0.1)
    assert trace["distance"][0] == 0 and trace["distance"][-1] == pytest.approx(145)
    assert set(trace["throttle"]) == {1.0} and set(trace["steer"]) == {-1.0}
    assert set(trace["gear"]) == {4}
    assert trace["lat_g"][0] == pytest.approx(1.0) and trace["lon_g"][0] == pytest.approx(-0.5)
    assert trace["susp_rear"][0] == pytest.approx(0.25)
    assert client.get(f"/api/laps/{lap['id']}/trace", params={"hz": 0}).status_code == 422


def test_patch_and_delete_session(client: TestClient) -> None:
    session = record_session(client)
    assert "tune_id" not in session
    patched = client.patch(f"/api/sessions/{session['id']}", json={"note": "wet"}).json()
    assert patched["note"] == "wet" and patched["lap_count"] == 3
    assert client.patch(f"/api/sessions/{session['id']}", json={}).json()["note"] == "wet"
    bad = client.patch(f"/api/sessions/{session['id']}", json={"tune_id": 1})
    assert bad.status_code == 422 and error_code(bad) == "validation_error"

    client.post("/api/recording/start")
    active_id = client.get("/api/status").json()["recording"]["session_id"]
    busy = client.delete(f"/api/sessions/{active_id}")
    assert busy.status_code == 409 and error_code(busy) == "session_recording"
    client.post("/api/recording/stop")

    assert client.delete(f"/api/sessions/{session['id']}").status_code == 204
    assert client.get(f"/api/sessions/{session['id']}").status_code == 404
    assert client.delete(f"/api/sessions/{session['id']}").status_code == 404


def test_settings(client: TestClient) -> None:
    defaults = client.get("/api/settings").json()
    assert defaults == {
        "units": {"speed": "kmh", "temperature": "C", "pressure": "bar"},
        "auto_record": False,
    }
    updated = client.put(
        "/api/settings", json={"units": {"speed": "mph"}, "auto_record": True}
    ).json()
    assert updated["units"] == {"speed": "mph", "temperature": "C", "pressure": "bar"}
    assert updated["auto_record"] is True
    assert client.app.state.services.recorder.auto_record is True
    bad = client.put("/api/settings", json={"units": {"speed": "knots"}})
    assert bad.status_code == 422 and error_code(bad) == "validation_error"


def test_auto_record_via_api(client: TestClient) -> None:
    client.put("/api/settings", json={"auto_record": True})
    inject(client, synth_laps(1))
    status = client.get("/api/status").json()["recording"]
    assert status["active"] and status["laps"] == 1


def test_tune_schema(client: TestClient) -> None:
    schema = client.get("/api/tune-schema").json()
    assert len(schema) == len(SETTINGS)
    assert schema[0] == {
        "key": "tires.pressure_front",
        "section": "Tires",
        "label": "Tire Pressure",
        "axle": "Front",
        "unit_imperial": "psi",
        "unit_metric": "bar",
        "drivetrains": ["FWD", "RWD", "AWD"],
    }


def test_unknown_api_path_is_json_404(client: TestClient) -> None:
    response = client.get("/api/nope")
    assert response.status_code == 404 and error_code(response) == "not_found"
    assert error_code(client.post("/api/status")) in {"not_found", "method_not_allowed"}


def test_shutdown_finishes_an_active_recording(tmp_path: Path) -> None:
    config = Config(data_dir=tmp_path / "data", web_dir=tmp_path / "no-web", live_hz=50.0)
    with TestClient(create_app(config, udp=False)) as client:
        client.post("/api/recording/start")
        inject(client, synth_laps(1))
    store = Store(tmp_path / "data")
    session = store.list_sessions()[0]
    assert session["stopped_at"] is not None
    assert [lap["kind"] for lap in store.list_laps(session["id"])] == ["flying", "partial"]
    store.close()


def test_tunes_are_gone(client: TestClient) -> None:
    for path in ("/api/tunes", "/api/tunes/active", "/api/tunes/1"):
        assert client.get(path).status_code == 404


# --- baseline setups ------------------------------------------------------------


def test_baselines_unavailable(client: TestClient) -> None:
    for path in ("/api/baseline/categories", "/api/baseline", "/api/baseline/lmp2"):
        response = client.get(path)
        assert response.status_code == 503 and error_code(response) == "baselines_unavailable"


def test_baseline_categories_and_manual_pick(app_factory: AppFactory) -> None:
    client = app_factory(baselines=fake_baselines())
    categories = client.get("/api/baseline/categories").json()
    assert [c["id"] for c in categories] == ["lmp2", "gt-awd"]
    assert categories[0] == {
        "id": "lmp2",
        "name": "LMP2",
        "description": "Prototypes",
        "divisions": ["Forza P2"],
        "drivetrains": ["RWD"],
    }
    picked = client.get("/api/baseline/gt-awd").json()
    assert picked["category"]["id"] == "gt-awd" and picked["unit_system"] == "metric"
    imperial = client.get("/api/baseline/gt-awd", params={"unit_system": "imperial"}).json()
    assert imperial["unit_system"] == "imperial"
    missing = client.get("/api/baseline/nope")
    assert missing.status_code == 404 and error_code(missing) == "not_found"
    bad_units = client.get("/api/baseline/lmp2", params={"unit_system": "furlongs"})
    assert bad_units.status_code == 422


def test_baseline_for_car_on_track(app_factory: AppFactory) -> None:
    baselines = fake_baselines()
    client = app_factory(baselines=baselines)
    assert client.get("/api/baseline").json() == {"match": None, "baseline": None}

    inject(client, synth_laps(0, tail_s=0.5))  # car 1234, known by ordinal
    result = client.get("/api/baseline").json()
    assert result["match"] == {
        "category_id": "lmp2",
        "how": "ordinal",
        "confidence": "high",
        "car": {"ordinal": 1234, "name": "Test Prototype", "division": "Forza P2"},
    }
    assert result["baseline"]["category"]["id"] == "lmp2"
    assert baselines.calls[-1] == (1234, 812, 6, 1)  # ordinal, PI, class index, drivetrain

    status = client.get("/api/status").json()
    assert status["car"]["name"] == "Test Prototype"
    assert status["car"]["division"] == "Forza P2"

    inject(client, synth_laps(0, tail_s=0.5, car_ordinal=555))  # unknown car, RWD
    assert client.get("/api/baseline").json() == {"match": None, "baseline": None}
    assert client.get("/api/status").json()["car"]["name"] is None
