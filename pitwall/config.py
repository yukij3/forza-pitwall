"""Runtime configuration from environment variables."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

APP_NAME = "forza-pitwall"


def is_frozen() -> bool:
    """True inside a PyInstaller bundle (the Windows desktop app)."""
    return bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS")


def resource_root(frozen: bool | None = None) -> Path:
    """Directory that holds ``pitwall/`` and ``web/``.

    The repository root from a checkout or the Docker image; the unpacked bundle
    (``sys._MEIPASS``) when frozen.
    """
    if is_frozen() if frozen is None else frozen:
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def default_data_dir(env: Mapping[str, str] | None = None, frozen: bool | None = None) -> Path:
    """``./data`` normally; ``%LOCALAPPDATA%\\forza-pitwall`` in the desktop app."""
    if not (is_frozen() if frozen is None else frozen):
        return Path("./data")
    env = os.environ if env is None else env
    base = env.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_NAME


REPO_ROOT = resource_root()


@dataclass(frozen=True, slots=True)
class Config:
    udp_port: int = 5300
    http_port: int = 5301
    bind: str = "0.0.0.0"
    data_dir: Path = Path("./data")
    public_host: str = ""
    live_hz: float = 20.0
    web_dir: Path = REPO_ROOT / "web"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        env = os.environ if env is None else env
        defaults = cls()

        def get(name: str) -> str | None:
            value = env.get(name)
            return value if value not in (None, "") else None

        return cls(
            udp_port=_int(get("PITWALL_UDP_PORT"), defaults.udp_port, "PITWALL_UDP_PORT"),
            http_port=_int(get("PITWALL_HTTP_PORT"), defaults.http_port, "PITWALL_HTTP_PORT"),
            bind=get("PITWALL_BIND") or defaults.bind,
            data_dir=Path(get("PITWALL_DATA_DIR") or default_data_dir(env)),
            public_host=get("PITWALL_PUBLIC_HOST") or defaults.public_host,
            live_hz=_float(get("PITWALL_LIVE_HZ"), defaults.live_hz, "PITWALL_LIVE_HZ"),
            web_dir=Path(get("PITWALL_WEB_DIR") or defaults.web_dir),
        )

    def with_overrides(self, **overrides: Any) -> Config:
        return replace(self, **{k: v for k, v in overrides.items() if v is not None})


def _int(value: str | None, default: int, name: str) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


def _float(value: str | None, default: float, name: str) -> float:
    if value is None:
        return default
    try:
        result = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {value!r}") from exc
    if result <= 0:
        raise ValueError(f"{name} must be positive")
    return result
