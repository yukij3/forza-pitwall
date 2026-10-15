"""Fixtures for core tests."""

from __future__ import annotations

import sys
import types
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pitwall.app import create_app
from pitwall.config import Config

AppFactory = Callable[..., TestClient]


@pytest.fixture
def app_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[AppFactory]:
    clients: list[TestClient] = []

    def make(
        *,
        engine: types.ModuleType | None = None,
        live: types.ModuleType | None = None,
        web_dir: Path | None = None,
        live_hz: float = 50.0,
    ) -> TestClient:
        # None makes the import fail, i.e. "analysis engine not installed".
        monkeypatch.setitem(sys.modules, "pitwall.analysis", engine)
        monkeypatch.setitem(sys.modules, "pitwall.analysis.live", live)
        config = Config(
            udp_port=0,
            http_port=0,
            bind="127.0.0.1",
            data_dir=tmp_path / "data",
            public_host="",
            live_hz=live_hz,
            web_dir=web_dir or tmp_path / "no-web",
        )
        client = TestClient(create_app(config, udp=False))
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(app_factory: AppFactory) -> TestClient:
    return app_factory()
