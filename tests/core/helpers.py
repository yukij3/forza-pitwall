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
    lap mid-way (as if recording began late). As in the game, the lap timer
    reads a few milliseconds (never exactly 0) on the first frame after the line.
    """
    t = time.monotonic() if t0 is None else t0
    race_clock = 0.0
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
                    current_lap=(j + 0.25) / HZ,
                    current_race_time=race_clock + 0.25 / HZ,
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
            race_clock += 1.0 / HZ
            distance += speed / HZ
        if idx < n_laps:
            last = duration
            best = last if best == 0 else min(best, last)
            if last_lap_lag == 0:
                shown_last = last
    return frames


def race_off(n: int, t0: float) -> list[Frame]:
    return [blank_frame(recv_time=t0 + i / HZ) for i in range(n)]


@dataclass
class Rewind:
    lap: int  # 0-based lap index
    at_s: float  # lap-timer seconds when the player rewinds
    back_s: float  # how far back the game goes
    gap_s: float = 7.0  # rewind screen: race-off packets for this long


def race_session(
    laps: int = 2,
    *,
    lap_m: float = 400.0,
    speed: float = 40.0,
    hz: float = 125.0,
    tick_hz: float = 60.0,
    t0: float = 1000.0,
    pre_race_s: float = 2.0,
    grid_m: float = 100.0,
    rewinds: Sequence[Rewind] = (),
    end: str = "finish",
    quit_at_m: float = 150.0,
) -> list[Frame]:
    """A race the way Forza Motorsport (2023) sends it, as seen in real recordings.

    * ``pre_race_s`` of race-on packets on the grid with the lap timer at exactly
      0, distance at ``-lap_m``, handbrake on, race clock left over from before;
    * lights out: race clock and lap timer start from ~0, the car accelerates
      from ``grid_m`` behind the start line; at the line the lap timer restarts
      while ``LapNumber`` stays 0;
    * ``laps`` laps at ``speed``; ``LastLap`` updates on the crossing packet;
    * ``rewinds``: race-off packets for ``gap_s``, then everything resumes
      ``back_s`` earlier;
    * ``end="finish"``: race-off on the last packet before the final line;
      ``end="quit"``: race-off ``quit_at_m`` into the last lap;
    * packets at ``hz`` with ``timestamp_ms`` ticking at ``tick_hz``, so
      consecutive packets often share a timestamp (as on PC).
    """
    frames: list[Frame] = []
    dt = 1.0 / hz
    recv = t0
    game_t = 0.0  # drives timestamp_ms

    def emit(**values: Any) -> None:
        nonlocal recv, game_t
        stamp = int(int(game_t * tick_hz) * 1000 / tick_hz)
        frames.append(
            blank_frame(
                recv_time=recv,
                is_race_on=True,
                timestamp_ms=stamp & 0xFFFFFFFF,
                engine_max_rpm=9000.0,
                current_engine_rpm=7000.0,
                gear=4,
                track_ordinal=TRACK,
                car_ordinal=CAR["car_ordinal"],
                car_pi=CAR["car_pi"],
                car_class=CAR["car_class"],
                drivetrain=CAR["drivetrain"],
                **values,
            )
        )
        recv += dt
        game_t += dt

    def off(seconds: float) -> None:
        nonlocal recv, game_t
        for _ in range(max(1, int(seconds * hz))):
            frames.append(blank_frame(recv_time=recv))
            recv += dt
        game_t += seconds

    # Pre-race on the grid.
    for i in range(int(pre_race_s * hz)):
        emit(current_race_time=40.0 + i * dt, distance_traveled=-lap_m, handbrake=255)

    # Lights out: accelerate from the grid to the line.
    accel = speed**2 / (2 * grid_m)
    clock = t_lap = 0.0
    dist, v = -grid_m, 0.0
    while dist < 0:
        clock += dt
        t_lap += dt
        v = min(speed, v + accel * dt)
        dist += v * dt
        emit(
            current_race_time=clock,
            current_lap=t_lap,
            distance_traveled=dist,
            speed=v,
            throttle=255,
        )

    # Laps: the timer restarts at the line.
    last = best = 0.0
    for lap in range(laps):
        start = lap * lap_m
        t_lap = 0.0
        dist = start + v * dt * 0.5
        pending = [r for r in rewinds if r.lap == lap]
        final = lap == laps - 1
        while True:
            clock += dt
            t_lap += dt
            dist += speed * dt
            if pending and t_lap >= pending[0].at_s:
                r = pending.pop(0)
                off(r.gap_s)
                clock -= r.back_s
                t_lap -= r.back_s
                dist -= speed * r.back_s
            if final and end == "quit" and dist - start >= quit_at_m:
                off(1.0)
                return frames
            if dist >= start + lap_m:
                if final:
                    off(1.0)  # chequered flag: race off, no lap increment
                    return frames
                break
            emit(
                lap_number=lap,
                current_race_time=clock,
                current_lap=t_lap,
                distance_traveled=dist,
                speed=speed,
                last_lap=last,
                best_lap=best,
                throttle=255,
            )
        # Crossing packet: new lap number, LastLap updated at once.
        last = round(t_lap, 3)
        best = last if best == 0 else min(best, last)
        overshoot = dist - (start + lap_m)
        v = speed
        emit(
            lap_number=lap + 1,
            current_race_time=clock,
            current_lap=overshoot / speed,
            distance_traveled=dist,
            speed=speed,
            last_lap=last,
            best_lap=best,
            throttle=255,
        )
    return frames


def segment(frames: Sequence[Frame]) -> list[Any]:
    """Run frames through a LapSegmenter the way the recorder does."""
    from pitwall.telemetry.laps import LapSegmenter

    seg = LapSegmenter(wall_clock=lambda: 0.0)
    out: list[Any] = []
    for i, frame in enumerate(frames):
        out += seg.add(frame, i) if frame.is_race_on else seg.note_race_off()
    return out + seg.finish()


# --- fake analysis engines ----------------------------------------------------


@dataclass
class FakeResult:
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return self.data


def fake_engine() -> types.ModuleType:
    """Mirrors the engine's contexts: tune fields exist but core must leave them empty."""
    mod = types.ModuleType("pitwall.analysis")

    @dataclass(frozen=True)
    class LapContext:
        drivetrain: str | int | None = None
        lap_kind: str = "flying"
        lap_valid: bool = True
        tune_values: dict[str, float] = field(default_factory=dict)
        unit_system: str = "imperial"
        lap_time: float | None = None

    @dataclass(frozen=True)
    class SessionContext:
        drivetrain: str | int | None = None
        tune_values: dict[str, float] = field(default_factory=dict)
        unit_system: str = "imperial"
        previous_session: Any = None
        tune_changes: Sequence[Any] = ()

    calls: dict[str, list[Any]] = {"lap": [], "session": []}

    def analyze_lap(frames: Sequence[Frame], ctx: LapContext) -> FakeResult:
        calls["lap"].append(ctx)
        return FakeResult({"kind": ctx.lap_kind, "metrics": {"frames": len(frames)}})

    def analyze_session(laps: Sequence[Any], ctx: SessionContext) -> FakeResult:
        calls["session"].append(ctx)
        return FakeResult({"laps_analyzed": len(laps)})

    mod.__version__ = "test"  # type: ignore[attr-defined]
    mod.LapContext = LapContext  # type: ignore[attr-defined]
    mod.SessionContext = SessionContext  # type: ignore[attr-defined]
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
            drivetrain: int | str,
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


def fake_baselines() -> types.ModuleType:
    """Baseline setups for two categories; knows one car by ordinal."""
    mod = types.ModuleType("pitwall.baselines")

    @dataclass
    class Category:  # plain dataclass: core falls back to asdict()
        id: str
        name: str
        description: str
        divisions: list[str]
        drivetrains: list[str]

    @dataclass
    class CarInfo:
        ordinal: int
        name: str
        division: str

    @dataclass
    class Match:
        category_id: str
        how: str
        confidence: str
        car: CarInfo | None

    cats = [
        Category("lmp2", "LMP2", "Prototypes", ["Forza P2"], ["RWD"]),
        Category("gt-awd", "GT AWD", "All-wheel-drive GT", ["GT"], ["AWD"]),
    ]
    cars = {1234: CarInfo(1234, "Test Prototype", "Forza P2")}
    calls: list[tuple[Any, ...]] = []

    def categories() -> list[Category]:
        return cats

    def match(car_ordinal, car_pi, car_class, drivetrain) -> Match | None:
        calls.append((car_ordinal, car_pi, car_class, drivetrain))
        if car_ordinal in cars:
            return Match("lmp2", "ordinal", "high", cars[car_ordinal])
        if drivetrain == 2:
            return Match("gt-awd", "class_drivetrain", "low", None)
        return None

    def baseline(category_id: str, unit_system: str = "imperial", drivetrain=None) -> FakeResult:
        category = next((c for c in cats if c.id == category_id), None)
        if category is None:
            raise KeyError(category_id)
        return FakeResult(
            {
                "category": vars(category),
                "unit_system": unit_system,
                "settings": [{"key": "arb.front", "value": 18.0}],
                "notes": [],
                "sources": [],
                "confidence": "low",
            }
        )

    def car_info(car_ordinal: int) -> CarInfo | None:
        return cars.get(car_ordinal)

    for fn in (categories, match, baseline, car_info):
        setattr(mod, fn.__name__, fn)
    mod.calls = calls  # type: ignore[attr-defined]
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
