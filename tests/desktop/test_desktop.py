"""Desktop app: frozen-mode paths, data dir, port checks and the smoke run.

pywebview is not needed: the window path is not exercised here.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

from pitwall import config as config_mod
from pitwall import desktop
from pitwall.config import Config, default_data_dir, resource_root


def _free_port(kind: int) -> int:
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# --- paths -----------------------------------------------------------------------


def test_resource_root_is_repo_when_not_frozen() -> None:
    root = resource_root(frozen=False)
    assert (root / "pitwall" / "config.py").is_file()
    assert (root / "web" / "index.html").is_file()


def test_resource_root_uses_meipass_when_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "/bundle", raising=False)
    assert config_mod.is_frozen()
    assert resource_root() == Path("/bundle")


def test_not_frozen_without_meipass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert not config_mod.is_frozen()


def test_baseline_data_resolves_from_resource_root() -> None:
    from pitwall.baselines import catalog

    assert resource_root() / "pitwall" / "baselines" / "data" == catalog.DATA_DIR
    assert (catalog.DATA_DIR / "categories.json").is_file()


# --- data dir ----------------------------------------------------------------------


def test_data_dir_default_unchanged_when_not_frozen() -> None:
    assert default_data_dir({"LOCALAPPDATA": r"C:\Users\x\AppData\Local"}, frozen=False) == Path(
        "./data"
    )
    assert Config.from_env({}).data_dir == Path("./data")


def test_data_dir_in_localappdata_when_frozen() -> None:
    env = {"LOCALAPPDATA": "/users/x/AppData/Local"}
    assert default_data_dir(env, frozen=True) == Path("/users/x/AppData/Local/forza-pitwall")


def test_data_dir_frozen_without_localappdata() -> None:
    expected = Path.home() / "AppData" / "Local" / "forza-pitwall"
    assert default_data_dir({}, frozen=True) == expected


def test_data_dir_env_wins_when_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "/bundle", raising=False)
    env = {"LOCALAPPDATA": "/local", "PITWALL_DATA_DIR": "/elsewhere"}
    assert Config.from_env(env).data_dir == Path("/elsewhere")
    assert Config.from_env({"LOCALAPPDATA": "/local"}).data_dir == Path("/local/forza-pitwall")


# --- desktop config -----------------------------------------------------------------


def test_desktop_config_defaults_public_host_to_loopback() -> None:
    config = desktop.desktop_config({})
    assert config.public_host == "127.0.0.1"
    assert config.bind == "0.0.0.0"  # UDP still reachable from the LAN
    assert desktop.base_url(config) == "http://127.0.0.1:5301"


def test_desktop_config_keeps_env_and_overrides() -> None:
    env = {"PITWALL_PUBLIC_HOST": "10.0.0.5", "PITWALL_HTTP_PORT": "6000"}
    config = desktop.desktop_config(env, {"udp_port": 7000, "data_dir": None})
    assert config.public_host == "10.0.0.5"
    assert (config.http_port, config.udp_port) == (6000, 7000)


def test_smoke_requested_by_flag_or_env() -> None:
    parse = desktop.build_parser().parse_args
    assert desktop.smoke_requested(parse(["--smoke"]), {})
    assert desktop.smoke_requested(parse([]), {"PITWALL_SMOKE": "1"})
    assert not desktop.smoke_requested(parse([]), {"PITWALL_SMOKE": "0"})
    assert not desktop.smoke_requested(parse([]), {})


# --- ports --------------------------------------------------------------------------


def test_port_conflicts_empty_when_free() -> None:
    config = Config(
        bind="127.0.0.1",
        http_port=_free_port(socket.SOCK_STREAM),
        udp_port=_free_port(socket.SOCK_DGRAM),
    )
    assert desktop.port_conflicts(config) == []


def test_port_conflicts_reports_taken_ports() -> None:
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp,
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp,
    ):
        tcp.bind(("127.0.0.1", 0))
        tcp.listen()
        udp.bind(("127.0.0.1", 0))
        config = Config(
            bind="127.0.0.1", http_port=tcp.getsockname()[1], udp_port=udp.getsockname()[1]
        )
        problems = desktop.port_conflicts(config)
    assert len(problems) == 2
    assert problems[0].startswith(f"HTTP port {config.http_port}")
    assert "PITWALL_HTTP_PORT" in problems[0]
    assert problems[1].startswith(f"UDP port {config.udp_port}")


# --- readiness and checks ---------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_wait_ready_retries_until_status_answers() -> None:
    clock = FakeClock()
    answers: list[object] = [OSError("refused"), OSError("refused"), {"receiver": {}}]

    def fetch(url: str) -> object:
        assert url == "http://x/api/status"
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    status = desktop.wait_ready(
        "http://x", lambda: True, fetch=fetch, sleep=clock.sleep, clock=clock
    )
    assert status == {"receiver": {}}
    assert answers == []


def test_wait_ready_fails_when_server_thread_dies() -> None:
    clock = FakeClock()

    def fetch(url: str) -> object:
        raise OSError("refused")

    with pytest.raises(desktop.StartupError, match="stopped during startup"):
        desktop.wait_ready("http://x", lambda: False, fetch=fetch, sleep=clock.sleep, clock=clock)


def test_wait_ready_times_out() -> None:
    clock = FakeClock()

    def fetch(url: str) -> object:
        raise OSError("refused")

    with pytest.raises(desktop.StartupError, match="did not answer within 5 s"):
        desktop.wait_ready(
            "http://x", lambda: True, timeout=5, fetch=fetch, sleep=clock.sleep, clock=clock
        )


def test_check_running_reports_each_part(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = {
        "http://x/api/status": {"receiver": {"listening": True, "udp_port": 5300}},
        "http://x/api/baseline/categories": [{"id": "a"}],
    }

    def fetch(url: str) -> object:
        if url not in responses:
            raise OSError("HTTP Error 503")
        return responses[url]

    monkeypatch.setattr(desktop, "_fetch_text", lambda url: "<!doctype html><html></html>")
    result = desktop.check_running("http://x", fetch=fetch)
    assert not result.ok  # analysis answered 503
    assert [line.split(":")[0] for line in result.lines] == [
        "ok   receiver",
        "ok   baselines",
        "FAIL analysis",
        "ok   web ui",
    ]


def test_check_window_toolkit_skipped_off_windows() -> None:
    assert desktop.check_window_toolkit("darwin") == (True, "skipped on darwin")


# --- end to end: the real server, headless ---------------------------------------


def test_smoke_runs_the_real_server(tmp_path: Path) -> None:
    config = desktop.desktop_config(
        {},
        {
            "bind": "127.0.0.1",
            "http_port": _free_port(socket.SOCK_STREAM),
            "udp_port": _free_port(socket.SOCK_DGRAM),
            "data_dir": tmp_path / "data",
        },
    )
    assert desktop.run_smoke(config, log_level="warning") == 0
    assert (tmp_path / "data").is_dir()
