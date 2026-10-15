from __future__ import annotations

import json
import time

import pytest

from pitwall.analysis import LiveAnalysis, LiveAnalyzer
from pitwall.analysis.assess import ITEMS
from pitwall.analysis.synthetic import ISSUES

from .data import DRIVETRAIN_CODE, EXPECTED, EXPECTED_CHANGE, exists_for, laps

BAD = ("warn", "bad")


def run(
    issue: str, drivetrain: str = "RWD", n_laps: int = 2, tune: dict[str, float] | None = None
) -> tuple[LiveAnalyzer, list[tuple[int, LiveAnalysis]]]:
    live = LiveAnalyzer(DRIVETRAIN_CODE[drivetrain], tune, unit_system="imperial")
    history = []
    for k, lap in enumerate(laps(issue, drivetrain)[:n_laps]):
        for frame in lap:
            snap = live.push(frame)
            if snap is not None:
                history.append((k, snap))
    return live, history


def test_starts_collecting() -> None:
    snap = LiveAnalyzer(1).snapshot()
    assert snap.corners_seen == 0 and snap.focus is None
    assert [i.id for i in snap.items] == [i for i, _, _ in ITEMS]
    assert all(i.status == "collecting" and i.recommendation is None for i in snap.items)


def test_clean_run_stays_ok() -> None:
    live, history = run("none", n_laps=3)
    assert history
    for _, snap in history:
        assert all(i.status in ("ok", "collecting") for i in snap.items)
        assert snap.focus is None
    final = live.snapshot()
    assert all(i.status == "ok" for i in final.items), [
        (i.id, i.status) for i in final.items if i.status != "ok"
    ]


@pytest.mark.parametrize("issue", sorted(EXPECTED))
def test_issue_turns_its_item_within_two_laps(issue: str) -> None:
    _, item_id = EXPECTED[issue]
    setting, direction = EXPECTED_CHANGE[(issue, "RWD")]
    live, history = run(issue)
    first = next((k for k, snap in history if snap.item(item_id).status in BAD), None)
    assert first is not None and first <= 1, f"{item_id} never left ok"
    snap = live.snapshot()
    item = snap.item(item_id)
    assert item.status in BAD
    assert item.recommendation is not None
    assert (item.recommendation.setting, item.recommendation.direction) == (setting, direction)
    assert snap.focus == item_id


@pytest.mark.parametrize("issue", ["wheelspin", "oversteer-exit", "oversteer-entry"])
@pytest.mark.parametrize("drivetrain", ["FWD", "AWD"])
def test_respects_the_drivetrain(issue: str, drivetrain: str) -> None:
    live, _ = run(issue, drivetrain)
    snap = live.snapshot()
    rec = snap.item(EXPECTED[issue][1]).recommendation
    assert rec is not None
    assert (rec.setting, rec.direction) == EXPECTED_CHANGE[(issue, drivetrain)]


@pytest.mark.parametrize("drivetrain", ["FWD", "RWD", "AWD"])
def test_never_a_setting_the_drivetrain_lacks(drivetrain: str) -> None:
    for issue in ISSUES:
        live, history = run(issue, drivetrain, n_laps=1)
        for _, snap in history:
            for item in snap.items:
                if item.recommendation is not None:
                    assert exists_for(item.recommendation.setting, drivetrain), (issue, item.id)


def test_exactly_one_focus_with_several_issues() -> None:
    live = LiveAnalyzer(1)
    from pitwall.analysis.synthetic import generate_laps

    for lap in generate_laps(["lockup-rear", "oversteer-exit"], 2, seed=5):
        for frame in lap:
            live.push(frame)
    snap = live.snapshot()
    flagged = {i.id for i in snap.items if i.status in BAD}
    assert {"lockups_rear", "exit_balance"} <= flagged
    assert isinstance(snap.focus, str) and snap.focus in flagged
    assert sum(1 for i in snap.items if i.id == snap.focus) == 1


def test_window_rolls_over_the_last_corners() -> None:
    live, _ = run("none", n_laps=3)
    snap = live.snapshot()
    assert snap.corners_seen == 24
    assert snap.window_corners == 12
    assert snap.window_laps is not None and 1.2 < snap.window_laps < 1.8


def test_reset_clears_the_window() -> None:
    live, _ = run("lockup-rear")
    assert live.snapshot().item("lockups_rear").status in BAD
    live.reset()
    snap = live.snapshot()
    assert snap.corners_seen == 0 and snap.window_corners == 0 and snap.focus is None
    assert all(i.status == "collecting" for i in snap.items)
    # after a "fix" the board starts from scratch
    for frame in laps("none")[2]:
        live.push(frame)
    assert live.snapshot().item("lockups_rear").status == "ok"


def test_board_recovers_after_a_fix_without_reset() -> None:
    live = LiveAnalyzer(1)
    for frame in laps("lockup-rear")[0]:
        live.push(frame)
    assert live.snapshot().item("lockups_rear").status in BAD
    for lap in laps("none")[1:]:
        for frame in lap:
            live.push(frame)
    assert live.snapshot().item("lockups_rear").status == "ok"


def test_suggested_value_uses_tune_values() -> None:
    live, _ = run("wheelspin", tune={"diff.accel_rear": 40.0})
    rec = live.snapshot().item("exit_wheelspin").recommendation
    assert rec is not None and rec.suggested_value == 35.0


def test_snapshots_only_when_something_completes() -> None:
    _, history = run("none", n_laps=1)
    frames = len(laps("none")[0])
    assert 10 <= len(history) <= 40 < frames


def test_to_dict_matches_the_contract() -> None:
    live, _ = run("understeer")
    data = json.loads(json.dumps(live.snapshot().to_dict()))
    assert set(data) == {"corners_seen", "window", "focus", "items"}
    assert set(data["window"]) == {"corners", "laps"}
    item = next(i for i in data["items"] if i["id"] == "mid_balance_low")
    assert set(item) >= {
        "id",
        "group",
        "title",
        "status",
        "value",
        "value_text",
        "target_text",
        "samples",
        "recommendation",
    }
    assert item["group"] == "Balance" and item["value_text"].startswith("Understeer")
    assert item["target_text"] == "−0.05 … +0.10"
    assert item["recommendation"]["text"] == "Anti-roll Bars → Front: −2"


def test_push_is_cheap() -> None:
    frames = [f for lap in laps("oversteer-exit")[:2] for f in lap]
    live = LiveAnalyzer(1)
    worst = 0.0
    start = time.perf_counter()
    for frame in frames:
        t0 = time.perf_counter()
        live.push(frame)
        worst = max(worst, time.perf_counter() - t0)
    per_frame = (time.perf_counter() - start) / len(frames)
    assert per_frame < 0.0001, f"{per_frame * 1e6:.1f} us per frame"
    assert worst < 0.03, f"slowest push {worst * 1e3:.1f} ms"


def test_ignores_frames_with_race_off() -> None:
    from dataclasses import replace

    live = LiveAnalyzer(1)
    for frame in laps("lockup-rear")[0][:3000]:
        assert live.push(replace(frame, is_race_on=False)) is None
    assert live.snapshot().corners_seen == 0
