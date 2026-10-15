"""Simulator, replay and the real UDP path."""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import pytest

from pitwall.storage.rawlog import RawWriter
from pitwall.telemetry.packet import FM2023_DASH_SIZE, canonical_gear, encode
from pitwall.telemetry.receiver import TelemetryReceiver, start_udp
from pitwall.tools.replay import replay
from pitwall.tools.simulator import ISSUES, SimOptions, build_track, simulate_frames
from pitwall.tools.udp import pace


def test_track_closes() -> None:
    track = build_track()
    assert abs(track.x[-1]) < 2 and abs(track.z[-1]) < 2
    assert 2500 < track.length < 3500


def test_simulated_laps() -> None:
    frames = list(simulate_frames(SimOptions(laps=2)))
    on = [f for f in frames if f.is_race_on]
    assert [f.lap_number for f in on][-1] == 2
    assert not frames[-1].is_race_on  # back in the menus at the end
    crossings = [b for a, b in zip(on, on[1:], strict=False) if b.lap_number != a.lap_number]
    assert len(crossings) == 2
    assert 55 < crossings[1].last_lap < 80
    assert on[0].speed < 1.0  # standing start: out lap
    assert {canonical_gear(f.gear) for f in on} >= {1, 2, 3, 4, 5}
    assert max(f.current_engine_rpm for f in on) <= on[0].engine_max_rpm
    assert all(len(encode(f)) == FM2023_DASH_SIZE for f in frames[:10])
    times = [f.recv_time for f in on[:61]]
    assert times[60] - times[0] == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("issue", "check"),
    [
        ("understeer", lambda f: abs(f.tire_slip_angle.fl) > 1.1),
        ("oversteer-exit", lambda f: abs(f.tire_slip_angle.rl) > 1.1),
        ("wheelspin", lambda f: f.tire_slip_ratio.rl > 1.1),
        ("lockup-rear", lambda f: f.tire_slip_ratio.rl < -1.1),
        ("bottoming", lambda f: f.susp_travel_norm.fl >= 1.0),
    ],
)
def test_issue_signatures(issue: str, check) -> None:
    def hits(name: str) -> int:
        return sum(1 for f in simulate_frames(SimOptions(laps=1, issue=name)) if check(f))

    assert hits(issue) > 20
    assert hits("none") == 0


def test_unknown_issue() -> None:
    assert "none" in ISSUES
    with pytest.raises(ValueError):
        next(simulate_frames(SimOptions(issue="flat-tire")))


def _udp_listener() -> tuple[socket.socket, int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(2.0)
    return sock, sock.getsockname()[1]


def test_pace_and_replay(tmp_path: Path) -> None:
    sock, port = _udp_listener()
    with sock:
        assert pace([(0.0, b"a"), (0.01, b"b"), (0.02, b"c")], "127.0.0.1", port, speedup=10) == 3
        assert [sock.recv(64) for _ in range(3)] == [b"a", b"b", b"c"]

        path = tmp_path / "s.pitwall"
        writer = RawWriter(path)
        frames = list(simulate_frames(SimOptions(laps=1)))[:20]
        for f in frames:
            writer.append(f.recv_time, encode(f))
        writer.close()
        assert replay(path, "127.0.0.1", port, speedup=50) == 20
        assert all(len(sock.recv(1024)) == FM2023_DASH_SIZE for _ in range(20))


async def test_receiver_over_real_udp() -> None:
    received = []
    receiver = TelemetryReceiver([lambda frame, raw: received.append(frame)])
    transport = await start_udp(receiver, "127.0.0.1", 0)
    try:
        port = transport.get_extra_info("sockname")[1]
        frames = list(simulate_frames(SimOptions(laps=1)))[:30]
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        with sender:
            for f in frames:
                sender.sendto(encode(f), ("127.0.0.1", port))
            sender.sendto(b"\x00" * 232, ("127.0.0.1", port))  # "Sled" format: ignored
            for _ in range(100):
                if len(received) == 30 and receiver.stats().ignored_packets == 1:
                    break
                await asyncio.sleep(0.01)
        stats = receiver.stats()
        assert receiver.listening and len(received) == 30
        assert stats.ignored_packets == 1 and stats.last_ignored_size == 232
        assert stats.packets_per_sec == 30 and stats.race_on
    finally:
        transport.close()
