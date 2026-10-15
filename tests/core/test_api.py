from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pitwall.tune.settings import SETTINGS

from .helpers import inject, race_off, synth_laps


def error_code(response) -> str:
    body = response.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message"}
    return body["error"]["code"]


def test_status_shape(client: TestClient) -> None:
    status = client.get("/api/status").json()
    assert set(status) == {"receiver", "recording", "car", "track_ordinal", "active_tune_id"}
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
    tune = client.post(
        "/api/tunes", json={"name": "Base", "unit_system": "metric", "values": {"arb.front": 20}}
    ).json()
    patched = client.patch(
        f"/api/sessions/{session['id']}", json={"note": "wet", "tune_id": tune["id"]}
    ).json()
    assert patched["note"] == "wet" and patched["tune_id"] == tune["id"]
    cleared = client.patch(f"/api/sessions/{session['id']}", json={"tune_id": None}).json()
    assert cleared["tune_id"] is None and cleared["note"] == "wet"
    bad = client.patch(f"/api/sessions/{session['id']}", json={"tune_id": 999})
    assert bad.status_code == 422 and error_code(bad) == "unknown_tune"

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


def test_tunes_versioning(client: TestClient) -> None:
    base = client.post(
        "/api/tunes",
        json={
            "name": "Baseline",
            "car_ordinal": 1234,
            "unit_system": "imperial",
            "values": {"arb.front": 20.0, "arb.rear": 18.0, "springs.front": 700.0},
        },
    ).json()
    assert base["parent_id"] is None and base["changes"] == []
    assert base["values"]["arb.front"] == 20.0 and base["created_at"]

    child = client.post(
        "/api/tunes",
        json={
            "name": "Baseline",
            "unit_system": "imperial",
            "values": {"arb.front": 18.0, "arb.rear": 18.0, "brake.balance": 52.0},
            "parent_id": base["id"],
            "note": "less push",
        },
    ).json()
    assert child["parent_id"] == base["id"] and child["car_ordinal"] == 1234
    assert child["changes"] == [
        {"setting": "arb.front", "from": 20.0, "to": 18.0},  # tuning-menu order
        {"setting": "springs.front", "from": 700.0, "to": None},
        {"setting": "brake.balance", "from": None, "to": 52.0},
    ]

    listed = client.get("/api/tunes").json()
    assert [t["id"] for t in listed] == [child["id"], base["id"]]
    assert all("values" not in t for t in listed)
    assert client.get("/api/tunes", params={"car_ordinal": 999}).json() == []
    assert client.get(f"/api/tunes/{child['id']}").json() == child
    assert error_code(client.get("/api/tunes/999")) == "not_found"


def test_tune_validation(client: TestClient) -> None:
    unknown = client.post(
        "/api/tunes", json={"name": "x", "unit_system": "metric", "values": {"arb.middle": 1}}
    )
    assert unknown.status_code == 422 and error_code(unknown) == "unknown_setting"
    parent = client.post("/api/tunes", json={"name": "x", "unit_system": "metric", "parent_id": 42})
    assert parent.status_code == 422 and error_code(parent) == "unknown_parent"
    units = client.post("/api/tunes", json={"name": "x", "unit_system": "furlongs"})
    assert units.status_code == 422 and error_code(units) == "validation_error"


def test_active_tune(client: TestClient) -> None:
    assert client.get("/api/tunes/active").json() is None
    base = client.post("/api/tunes", json={"name": "A", "unit_system": "metric"}).json()
    other = client.post("/api/tunes", json={"name": "B", "unit_system": "metric"}).json()
    assert client.put("/api/tunes/active", json={"tune_id": base["id"]}).json()["id"] == base["id"]
    assert client.get("/api/status").json()["active_tune_id"] == base["id"]

    # A new version of the active tune becomes active; a version of another doesn't.
    child = client.post(
        "/api/tunes", json={"name": "A", "unit_system": "metric", "parent_id": base["id"]}
    ).json()
    assert client.get("/api/tunes/active").json()["id"] == child["id"]
    client.post("/api/tunes", json={"name": "B", "unit_system": "metric", "parent_id": other["id"]})
    assert client.get("/api/tunes/active").json()["id"] == child["id"]

    session = record_session(client)
    assert session["tune_id"] == child["id"]

    assert client.put("/api/tunes/active", json={"tune_id": None}).json() is None
    assert client.get("/api/status").json()["active_tune_id"] is None
    assert client.put("/api/tunes/active", json={"tune_id": 999}).status_code == 404


def test_unknown_api_path_is_json_404(client: TestClient) -> None:
    response = client.get("/api/nope")
    assert response.status_code == 404 and error_code(response) == "not_found"
    assert error_code(client.post("/api/status")) in {"not_found", "method_not_allowed"}
