"""Command line: ``python -m pitwall serve | simulate | replay``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pitwall.config import Config


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from pitwall.app import create_app

    config = Config.from_env().with_overrides(
        udp_port=args.udp_port,
        http_port=args.http_port,
        bind=args.bind,
        data_dir=args.data_dir,
        web_dir=args.web_dir,
    )
    app = create_app(config)
    uvicorn.run(app, host=config.bind, port=config.http_port, log_level=args.log_level)
    return 0


def _simulate(args: argparse.Namespace) -> int:
    from pitwall.tools.simulator import SimOptions, send, simulate_frames

    opts = SimOptions(laps=args.laps, issue=args.issue, seed=args.seed)
    laps = "endless" if args.laps == 0 else f"{args.laps} lap(s)"
    print(f"simulating {laps}, issue={args.issue}, x{args.speedup} -> {args.host}:{args.port}")
    try:
        sent = send(simulate_frames(opts), args.host, args.port, speedup=args.speedup, fm7=args.fm7)
    except KeyboardInterrupt:
        return 130
    print(f"sent {sent} packets")
    return 0


def _replay(args: argparse.Namespace) -> int:
    from pitwall.tools.replay import replay

    print(f"replaying {args.file} x{args.speedup} -> {args.host}:{args.port}")
    try:
        sent = replay(args.file, args.host, args.port, speedup=args.speedup)
    except KeyboardInterrupt:
        return 130
    print(f"sent {sent} packets")
    return 0


def build_parser() -> argparse.ArgumentParser:
    from pitwall.tools.simulator import ISSUES

    env = Config.from_env()
    parser = argparse.ArgumentParser(prog="pitwall", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the receiver, recorder, API and web UI")
    serve.add_argument("--udp-port", type=int, help="Data Out port (env PITWALL_UDP_PORT)")
    serve.add_argument("--http-port", type=int, help="web/API port (env PITWALL_HTTP_PORT)")
    serve.add_argument("--bind", help="bind address (env PITWALL_BIND)")
    serve.add_argument("--data-dir", type=Path, help="data directory (env PITWALL_DATA_DIR)")
    serve.add_argument("--web-dir", type=Path, help="static UI directory (env PITWALL_WEB_DIR)")
    serve.add_argument("--log-level", default="info")
    serve.set_defaults(func=_serve)

    sim = sub.add_parser("simulate", help="send synthetic Car Dash packets")
    sim.add_argument("--host", default="127.0.0.1")
    sim.add_argument("--port", type=int, default=env.udp_port)
    sim.add_argument("--laps", type=int, default=5, help="line crossings; 0 = endless")
    sim.add_argument("--issue", choices=ISSUES, default="none")
    sim.add_argument("--speedup", type=float, default=1.0)
    sim.add_argument("--seed", type=int, default=1)
    sim.add_argument("--fm7", action="store_true", help="send 311-byte FM7 packets")
    sim.set_defaults(func=_simulate)

    rep = sub.add_parser("replay", help="resend a recorded raw packet file")
    rep.add_argument("file", type=Path, help="raw packet file (data/raw/session-N.pitwall)")
    rep.add_argument("--host", default="127.0.0.1")
    rep.add_argument("--port", type=int, default=env.udp_port)
    rep.add_argument("--speedup", type=float, default=1.0)
    rep.set_defaults(func=_replay)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
