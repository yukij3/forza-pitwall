"""Helpers for core tests: synthetic laps, fake engines, frame injection."""

from __future__ import annotations

import time
import types
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from fastapi.testclient import TestClient

from pitwall.telemetry.model import Corners, Frame
from pitwall.telemetry.packet import blank_frame, encode

HZ = 60
CAR = {"car_ordinal": 1234, "car_pi": 812, "car_class": 6, "drivetrain": 1}
TRACK = 860


def synth_laps(
    n_laps: int,
    *,
    lap_s: float = 3.0,
    t0: float | None = None,
    start_lap: int = 0,
    standing_start: bool = False,
    last_lap_lag: int = 1,
    tail_s: float = 1.5,
    start_offset_s: float = 0.0,
    car_ordinal: int = CAR["car_ordinal"],
    track_ordinal: int = TRACK,
) -> list[Frame]:
    """Frames for ``n_laps`` complete laps plus a tail into the next lap.

    Lap k lasts ``lap_s + 0.01 * k`` seconds. ``last_lap`` updates
    ``last_lap_lag`` frames after the line. ``start_offset_s`` starts the first
    lap mid-way (as if recording began late).
    """
    t = time.monotonic() if t0 is None else t0
    frames: list[Frame] = []
    distance = 0.0
    last = best = shown_last = 0.0
    for idx in range(n_laps + 1):
        duration = lap_s + 0.01 * idx if idx < n_laps else tail_s
        first_j = int(start_offset_s * HZ) if idx == 0 else 0
        for j in range(first_j, int(duration * HZ)):
            if j == last_lap_lag:
                shown_last = last
            speed = min(50.0, 2.0 + j * 1.0) if (standing_start and idx == 0) else 50.0
            frames.append(
                blank_frame(
                    recv_time=t,
                    is_race_on=True,
                    timestamp_ms=int(t * 1000) & 0xFFFFFFFF,
                    engine_max_rpm=9000.0,
                    current_engine_rpm=7000.0,
                    accel_x=9.81,
                    accel_z=-4.905,
                    lap_number=start_lap + idx,
                    current_lap=j / HZ,
                    last_lap=shown_last,
                    best_lap=best,
                    distance_traveled=distance,
                    speed=speed,
                    throttle=255,
                    brake=0,
                    gear=4,
                    steer=-127,
                    tire_temp=Corners(212.0, 212.0, 176.0, 176.0),
                    tire_wear=Corners(1.0, 1.0, 0.5, 0.5),
                    susp_travel_norm=Corners(0.5, 0.5, 0.25, 0.25),
                    track_ordinal=track_ordinal,
                    car_ordinal=car_ordinal,
                    car_pi=CAR["car_pi"],
                    car_class=CAR["car_class"],
                    drivetrain=CAR["drivetrain"],
                )
            )
            t += 1.0 / HZ
            distance += speed / HZ
        if idx < n_laps:
            last = duration
            best = last if best == 0 else min(best, last)
            if last_lap_lag == 0:
                shown_last = last
    return frames


def race_off(n: int, t0: float) -> list[Frame]:
    return [blank_frame(recv_time=t0 + i / HZ) for i in range(n)]


# --- fake analysis engines ----------------------------------------------------


@dataclass
class FakeResult:
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return self.data


def fake_engine() -> types.ModuleType:
    mod = types.ModuleType("pitwall.analysis")

    @dataclass
    class LapContext:
        drivetrain: int
        lap_kind: str
        lap_valid: bool
        tune_values: dict[str, float]
        unit_system: str

    @dataclass
    class TuneChange:
        setting: str
        from_value: float | None
        to_value: float | None

    @dataclass
    class SessionContext:
        drivetrain: int
        tune_values: dict[str, float]
        unit_system: str
        previous_session: Any = None
        tune_changes: Sequence[TuneChange] = field(default_factory=list)

    calls: dict[str, list[Any]] = {"lap": [], "session": []}

    def analyze_lap(frames: Sequence[Frame], ctx: LapContext) -> FakeResult:
        calls["lap"].append(ctx)
        return FakeResult({"kind": ctx.lap_kind, "metrics": {"frames": len(frames)}})

    def analyze_session(laps: Sequence[Any], ctx: SessionContext) -> FakeResult:
        calls["session"].append(ctx)
        return FakeResult(
            {
                "laps_analyzed": len(laps),
                "has_previous": ctx.previous_session is not None,
                "tune_changes": [vars(c) for c in ctx.tune_changes],
            }
        )

    mod.LapContext = LapContext  # type: ignore[attr-defined]
    mod.SessionContext = SessionContext  # type: ignore[attr-defined]
    mod.TuneChange = TuneChange  # type: ignore[attr-defined]
    mod.analyze_lap = analyze_lap  # type: ignore[attr-defined]
    mod.analyze_session = analyze_session  # type: ignore[attr-defined]
    mod.calls = calls  # type: ignore[attr-defined]
    return mod


def fake_live(every: int = 30) -> types.ModuleType:
    """A LiveAnalyzer that reports a new snapshot every ``every`` frames."""
    mod = types.ModuleType("pitwall.analysis.live")
    instances: list[Any] = []

    class LiveAnalyzer:
        def __init__(
            self,
            drivetrain: int,
            tune_values: dict[str, float] | None = None,
            unit_system: str = "imperial",
            window_corners: int = 12,
        ) -> None:
            self.drivetrain = drivetrain
            self.tune_values = dict(tune_values or {})
            self.unit_system = unit_system
            self.pushed = 0
            instances.append(self)

        def push(self, frame: Frame) -> FakeResult | None:
            self.pushed += 1
            return self.snapshot() if self.pushed % every == 0 else None

        def snapshot(self) -> FakeResult:
            return FakeResult(
                {
                    "corners_seen": self.pushed // every,
                    "window": {"corners": 12, "laps": 0.0},
                    "focus": None,
                    "items": [],
                }
            )

        def reset(self) -> None:
            self.pushed = 0

    mod.LiveAnalyzer = LiveAnalyzer  # type: ignore[attr-defined]
    mod.instances = instances  # type: ignore[attr-defined]
    return mod


# --- app clients --------------------------------------------------------------


def inject(client: TestClient, frames: Sequence[Frame]) -> None:
    """Feed frames through the receiver on the app's event loop thread."""
    receiver = client.app.state.services.receiver  # type: ignore[attr-defined]
    packets = [(encode(f), f.recv_time) for f in frames]

    def run() -> None:
        for payload, recv_time in packets:
            receiver.handle_packet(payload, recv_time)

    assert client.portal is not None
    client.portal.call(run)
