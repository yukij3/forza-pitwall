"""Desktop app: the Pitwall server in a background thread, the UI in a native window.

This is the entrypoint of the Windows build (PyInstaller + pywebview/WebView2).
It reuses the normal server: same ``Config`` (``PITWALL_*`` env vars), same app.
Differences from ``python -m pitwall serve``:

- the web UI/API listens on ``127.0.0.1`` only; the UDP receiver still binds
  ``PITWALL_BIND`` (default ``0.0.0.0``) so the game can send from this PC or
  from the LAN;
- when frozen, data goes to ``%LOCALAPPDATA%\\forza-pitwall`` (see
  ``pitwall.config.default_data_dir``) and a log file is written there;
- ``--smoke`` starts the server headless, checks it, and exits 0 or 1 (CI).

pywebview is imported lazily, so this module imports fine without it.
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pitwall import __version__
from pitwall.config import Config, is_frozen

log = logging.getLogger("pitwall.desktop")

WINDOW_TITLE = "Forza Pitwall"
WINDOW_SIZE = (1440, 900)
WINDOW_MIN_SIZE = (960, 600)
HTTP_HOST = "127.0.0.1"
READY_TIMEOUT_S = 30.0
STOP_TIMEOUT_S = 10.0
LOG_FILE = "pitwall-desktop.log"


class StartupError(Exception):
    """The server could not start; the message is shown to the user."""


def desktop_config(
    env: Mapping[str, str] | None = None, overrides: Mapping[str, Any] | None = None
) -> Config:
    """``Config.from_env`` plus desktop defaults.

    The setup hint shows ``127.0.0.1`` unless ``PITWALL_PUBLIC_HOST`` is set: the
    game usually runs on the same PC as the app.
    """
    config = Config.from_env(env).with_overrides(**(overrides or {}))
    if not config.public_host:
        config = config.with_overrides(public_host=HTTP_HOST)
    return config


def base_url(config: Config) -> str:
    return f"http://{HTTP_HOST}:{config.http_port}"


# --- port checks ---------------------------------------------------------------


def port_conflicts(config: Config) -> list[str]:
    """Human-readable problems with the ports, empty if both are free.

    Binds without SO_REUSEADDR, like asyncio does on Windows, so a port held by
    another process (often a second Pitwall) is reported before the server starts.
    """
    problems: list[str] = []
    checks = (
        (socket.SOCK_STREAM, HTTP_HOST, config.http_port, "HTTP", "PITWALL_HTTP_PORT"),
        (socket.SOCK_DGRAM, config.bind, config.udp_port, "UDP", "PITWALL_UDP_PORT"),
    )
    for kind, host, port, label, env_name in checks:
        if port == 0:
            continue
        try:
            with socket.socket(_family(host), kind) as sock:
                sock.bind((host, port))
        except OSError as exc:
            problems.append(
                f"{label} port {port} on {host} is not available ({exc.strerror or exc}). "
                f"Close the other program using it (is Pitwall already running?) "
                f"or set {env_name} to another port."
            )
    return problems


def _family(host: str) -> socket.AddressFamily:
    return socket.AF_INET6 if ":" in host else socket.AF_INET


# --- server in a background thread --------------------------------------------


class ServerThread:
    """uvicorn serving the Pitwall app in a daemon thread."""

    def __init__(self, config: Config, log_level: str = "info") -> None:
        import uvicorn

        from pitwall.app import create_app

        self.config = config
        self.server = uvicorn.Server(
            uvicorn.Config(
                create_app(config),
                host=HTTP_HOST,
                port=config.http_port,
                log_level=log_level,
                # Our logging setup, not uvicorn's: its formatter calls
                # sys.stdout.isatty(), and stdout is None in a windowed exe.
                log_config=None,
                timeout_graceful_shutdown=5,
            )
        )
        self.thread = threading.Thread(target=self.server.run, name="pitwall-server", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def alive(self) -> bool:
        return self.thread.is_alive()

    def stop(self, timeout: float = STOP_TIMEOUT_S) -> bool:
        """Ask uvicorn to exit (runs the app's shutdown); True if it stopped in time."""
        self.server.should_exit = True
        if self.thread.is_alive():
            self.thread.join(timeout)
        return not self.thread.is_alive()


def fetch_json(url: str, timeout: float = 2.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (local URL)
        return json.loads(resp.read().decode("utf-8"))


def wait_ready(
    url: str,
    alive: Callable[[], bool],
    timeout: float = READY_TIMEOUT_S,
    fetch: Callable[[str], Any] = fetch_json,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Poll ``{url}/api/status`` until it answers; raise ``StartupError`` otherwise."""
    deadline = clock() + timeout
    last_error = "no answer"
    while True:
        try:
            status = fetch(f"{url}/api/status")
        except (OSError, ValueError) as exc:
            last_error = str(exc)
        else:
            if isinstance(status, dict):
                return status
            last_error = f"unexpected /api/status response: {status!r}"
        if not alive():
            raise StartupError(f"The Pitwall server stopped during startup ({last_error}).")
        if clock() >= deadline:
            raise StartupError(
                f"The Pitwall server did not answer within {timeout:.0f} s ({last_error})."
            )
        sleep(0.2)


# --- smoke test -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SmokeResult:
    ok: bool
    lines: list[str]


def check_running(url: str, fetch: Callable[[str], Any] = fetch_json) -> SmokeResult:
    """Checks for a started server: status, UDP receiver, bundled UI and data."""
    lines: list[str] = []
    ok = True

    def check(name: str, passed: bool, detail: str) -> None:
        nonlocal ok
        ok = ok and passed
        lines.append(f"{'ok  ' if passed else 'FAIL'} {name}: {detail}")

    try:
        status = fetch(f"{url}/api/status")
        receiver = status.get("receiver", {})
        check(
            "receiver",
            bool(receiver.get("listening")),
            f"listening={receiver.get('listening')} udp_port={receiver.get('udp_port')}",
        )
    except Exception as exc:  # noqa: BLE001 (reported, not raised)
        check("status", False, repr(exc))
    # Both modules are imported lazily by name: a bundle that misses them answers 503.
    try:
        categories = fetch(f"{url}/api/baseline/categories")
        check("baselines", bool(categories), f"{len(categories)} categories")
    except Exception as exc:  # noqa: BLE001
        check("baselines", False, repr(exc))
    try:
        board = fetch(f"{url}/api/live-analysis")
        check("analysis", isinstance(board, dict), f"live board with {len(board)} keys")
    except Exception as exc:  # noqa: BLE001
        check("analysis", False, repr(exc))
    try:
        html = _fetch_text(f"{url}/")
        bundled = "<html" in html.lower() and "PITWALL_WEB_DIR" not in html  # not the placeholder
        check("web ui", bundled, f"{len(html)} bytes")
    except Exception as exc:  # noqa: BLE001
        check("web ui", False, repr(exc))
    return SmokeResult(ok, lines)


def _fetch_text(url: str, timeout: float = 2.0) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (local URL)
        return resp.read().decode("utf-8", errors="replace")


def check_window_toolkit(platform: str = sys.platform) -> tuple[bool, str]:
    """Load the native window backend without opening a window.

    On Windows this imports pywebview's WebView2 backend, which loads pythonnet
    and the bundled WebView2 interop DLLs: the parts a PyInstaller build can miss.
    Elsewhere the desktop build is not supported, so the check is skipped.
    """
    if platform != "win32":
        return True, f"skipped on {platform}"
    try:
        importlib.import_module("webview.platforms.edgechromium")
    except Exception as exc:  # noqa: BLE001 (reported, not raised)
        return False, repr(exc)
    return True, "pywebview WebView2 backend loads"


def run_smoke(config: Config, log_level: str = "info") -> int:
    log.info("smoke test: pitwall %s, data dir %s", __version__, config.data_dir.resolve())
    if problems := port_conflicts(config):
        for problem in problems:
            log.error("%s", problem)
        return 1
    server = ServerThread(config, log_level)
    server.start()
    try:
        wait_ready(base_url(config), server.alive)
        result = check_running(base_url(config))
    except StartupError as exc:
        log.error("%s", exc)
        result = SmokeResult(False, [])
    finally:
        stopped = server.stop()
    gui_ok, gui_detail = check_window_toolkit()
    result = SmokeResult(
        result.ok and gui_ok,
        [*result.lines, f"{'ok  ' if gui_ok else 'FAIL'} window: {gui_detail}"],
    )
    for line in result.lines:
        log.info("smoke %s", line)
    if not stopped:
        log.error("smoke: server did not stop within %.0f s", STOP_TIMEOUT_S)
    ok = result.ok and stopped
    log.info("smoke test %s", "passed" if ok else "FAILED")
    return 0 if ok else 1


# --- window --------------------------------------------------------------------


def run_window(config: Config, log_level: str = "info") -> int:
    if problems := port_conflicts(config):
        show_error("\n\n".join(problems))
        return 1
    try:
        import webview
    except ImportError:
        show_error("pywebview is not installed. Install the 'desktop' dependency group.")
        return 1

    server = ServerThread(config, log_level)
    server.start()
    try:
        wait_ready(base_url(config), server.alive)
    except StartupError as exc:
        server.stop()
        show_error(f"{exc}\n\nLog: {log_path(config)}")
        return 1

    log.info("opening window at %s", base_url(config))
    webview.create_window(
        WINDOW_TITLE,
        base_url(config),
        width=WINDOW_SIZE[0],
        height=WINDOW_SIZE[1],
        min_size=WINDOW_MIN_SIZE,
        resizable=True,
        background_color="#111111",
    )
    try:
        # Blocks until the window is closed. A persistent profile keeps the UI's
        # local state (e.g. units) between runs.
        webview.start(private_mode=False, storage_path=str(config.data_dir / "webview"))
    finally:
        log.info("window closed, stopping the server")
        if not server.stop():
            log.warning("server did not stop within %.0f s", STOP_TIMEOUT_S)
    return 0


def show_error(message: str) -> None:
    """Error for the user: a message box on Windows, stderr elsewhere."""
    log.error("%s", message)
    if sys.platform == "win32":
        import ctypes

        mb_iconerror = 0x10
        ctypes.windll.user32.MessageBoxW(None, message, WINDOW_TITLE, mb_iconerror)
    elif sys.stderr is not None:
        print(message, file=sys.stderr)


# --- logging and entrypoint -----------------------------------------------------


def log_path(config: Config) -> Path:
    return config.data_dir / LOG_FILE


def setup_logging(config: Config, level: str) -> None:
    """Log to stderr when there is one, and to a file in the data directory.

    A windowed PyInstaller exe has ``sys.stdout``/``sys.stderr`` set to None;
    they are pointed at os.devnull so stray prints don't crash.
    """
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    try:
        config.data_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path(config), mode="w", encoding="utf-8"))
    except OSError:
        pass  # the server reports an unusable data dir itself
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forza-pitwall", description="Pitwall desktop app (server + native window)."
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="start the server without a window, check it, exit 0/1 (env PITWALL_SMOKE=1)",
    )
    parser.add_argument("--udp-port", type=int, help="Data Out port (env PITWALL_UDP_PORT)")
    parser.add_argument("--http-port", type=int, help="local UI/API port (env PITWALL_HTTP_PORT)")
    parser.add_argument("--data-dir", type=Path, help="data directory (env PITWALL_DATA_DIR)")
    parser.add_argument("--log-level", default="info")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def smoke_requested(args: argparse.Namespace, env: Mapping[str, str]) -> bool:
    return bool(args.smoke) or env.get("PITWALL_SMOKE", "") not in ("", "0")


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    args = build_parser().parse_args(argv)
    try:
        config = desktop_config(
            env,
            {"udp_port": args.udp_port, "http_port": args.http_port, "data_dir": args.data_dir},
        )
    except ValueError as exc:  # bad PITWALL_* value
        show_error(str(exc))
        return 1
    setup_logging(config, args.log_level)
    log.info(
        "pitwall %s desktop (frozen=%s), data dir %s",
        __version__,
        is_frozen(),
        config.data_dir.resolve(),
    )
    if smoke_requested(args, env):
        return run_smoke(config, args.log_level)
    return run_window(config, args.log_level)


if __name__ == "__main__":
    sys.exit(main())
