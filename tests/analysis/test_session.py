from __future__ import annotations

import json
from dataclasses import replace

import pytest

from pitwall.analysis import SessionContext, TuneChange, analyze_session
from pitwall.analysis.synthetic import ISSUES

from .data import EXPECTED, EXPECTED_CHANGE, exists_for, lap_analyses, session


def test_clean_session_has_no_next_change() -> None:
    sa = session("none")
    assert sa.laps_analyzed == 3
    assert sa.findings == ()
    assert sa.next_change is None and sa.alternatives == ()
    assert sa.verdict_on_last_change is None
    assert any("Heat" in limit for limit in sa.limits)


@pytest.mark.parametrize("issue", sorted(EXPECTED))
@pytest.mark.parametrize("drivetrain", ["FWD", "RWD", "AWD"])
def test_injected_issue_gives_the_next_change(issue: str, drivetrain: str) -> None:
    sa = session(issue, drivetrain)
    nc = sa.next_change
    assert nc is not None
    assert nc.finding_id == EXPECTED[issue][0]
    assert (nc.setting, nc.direction) == EXPECTED_CHANGE[(issue, drivetrain)]
    assert nc.priority == 1 and nc.confidence >= 0.35
    assert nc.suggested_value is None  # no tune values entered
    assert sa.findings[0].id == nc.finding_id
    assert sa.findings[0].laps == 3 and sa.findings[0].consistency == 1.0
    assert len(sa.alternatives) <= 2
    settings = [nc.setting, *(a.setting for a in sa.alternatives)]
    assert len(settings) == len(set(settings)), "alternatives are different settings"


@pytest.mark.parametrize("drivetrain", ["FWD", "RWD", "AWD"])
def test_never_recommends_a_setting_the_drivetrain_lacks(drivetrain: str) -> None:
    for issue in ISSUES:
        sa = session(issue, drivetrain)
        recs = [r for r in (sa.next_change, *sa.alternatives) if r is not None]
        recs += [r for la in lap_analyses(issue, drivetrain) for r in la.recommendations]
        assert all(exists_for(r.setting, drivetrain) for r in recs), (issue, drivetrain)


def test_suggested_value_from_tune_sheet() -> None:
    laps = lap_analyses("oversteer-exit")
    sa = analyze_session(
        laps, SessionContext(drivetrain=1, tune_values={"diff.accel_rear": 40.0, "arb.rear": 20})
    )
    assert sa.next_change is not None
    assert sa.next_change.suggested_value == 35.0
    assert sa.next_change.text == "Differential → Acceleration (Rear): −5%"
    alt = {a.setting: a for a in sa.alternatives}
    assert alt["arb.rear"].suggested_value == 18.0


def test_setting_at_its_limit_falls_back_to_the_next_rule() -> None:
    laps = lap_analyses("oversteer-exit")
    sa = analyze_session(laps, SessionContext(drivetrain=1, tune_values={"diff.accel_rear": 0.0}))
    assert sa.next_change is not None and sa.next_change.setting == "arb.rear"


def test_aero_advice_drops_when_the_tune_sheet_has_no_aero() -> None:
    laps = lap_analyses("high-speed-understeer")
    sa = analyze_session(laps, SessionContext(drivetrain=1, tune_values={"arb.front": 22.0}))
    assert sa.next_change is not None
    assert sa.next_change.setting == "arb.front" and sa.next_change.suggested_value == 20.0
    assert "aero.front" in {a.setting for a in sa.alternatives}


def test_only_valid_flying_laps_count() -> None:
    bad = lap_analyses("lockup-rear")
    clean = lap_analyses("none")
    laps = [replace(bad[0], lap_kind="out"), replace(bad[1], valid=False), *clean]
    sa = analyze_session(laps, SessionContext(drivetrain=1))
    assert sa.laps_analyzed == 3
    assert sa.next_change is None
    assert sa.consistency["laps_total"] == 5 and sa.consistency["laps_valid"] == 3


def test_no_valid_laps() -> None:
    laps = [replace(la, valid=False) for la in lap_analyses("understeer")]
    sa = analyze_session(laps, SessionContext(drivetrain=1))
    assert sa.laps_analyzed == 0 and sa.next_change is None and sa.findings == ()
    assert sa.limits[0].startswith("No valid flying laps")


def test_one_off_issue_is_not_a_finding() -> None:
    laps = [lap_analyses("wheelspin")[1], *lap_analyses("none")]
    sa = analyze_session(laps, SessionContext(drivetrain=1))
    assert sa.next_change is None


def test_single_lap_lowers_confidence() -> None:
    one = analyze_session(lap_analyses("understeer")[1:2], SessionContext(drivetrain=1))
    three = session("understeer")
    assert one.next_change is not None and three.next_change is not None
    assert one.next_change.confidence < three.next_change.confidence
    assert any("provisional" in limit for limit in one.limits)


def test_consistency_block() -> None:
    c = session("none").consistency
    assert c["laps_valid"] == 3 and len(c["lap_times"]) == 3
    assert c["best"] <= c["median"] and c["stdev"] >= 0
    assert c["rating"] in ("consistent", "variable", "inconsistent")
    assert c["lap_numbers"] == [1, 2, 3]


# --- Verdict on the last change ---------------------------------------------------
def _ctx(previous, changes=(), tune=None):
    return SessionContext(
        drivetrain=1, tune_values=tune or {}, previous_session=previous, tune_changes=changes
    )


def test_verdict_helped() -> None:
    before = session("understeer")
    change = TuneChange("arb.front", 20.0, 18.0)
    sa = analyze_session(lap_analyses("none"), _ctx(before, [change], {"arb.front": 18.0}))
    v = sa.verdict_on_last_change
    assert v is not None and v.result == "helped"
    assert v.lap_time_delta is not None and v.lap_time_delta < -0.3
    assert v.finding_deltas["mid-understeer"]["after"] == 0.0
    assert v.text.startswith("Helped: −")
    assert "mid-corner understeer gone" in v.text
    assert "Anti-roll Bars → Front: 20 → 18" in v.text
    data = json.loads(json.dumps(sa.to_dict()))["verdict_on_last_change"]
    assert data["changes"] == [{"setting": "arb.front", "from": 20.0, "to": 18.0}]


def test_verdict_hurt_suggests_a_revert() -> None:
    before = session("none")
    change = TuneChange("arb.front", 18.0, 20.0)
    sa = analyze_session(lap_analyses("understeer"), _ctx(before, [change], {"arb.front": 20.0}))
    v = sa.verdict_on_last_change
    assert v is not None and v.result == "hurt"
    assert "new: mid-corner understeer" in v.text
    nc = sa.next_change
    assert nc is not None and nc.id == "revert-arb-front"
    assert nc.reason.startswith("Last change hurt · ") and len(nc.reason) <= 64
    assert nc.detail and "Undo it" in nc.detail
    assert (nc.setting, nc.direction, nc.step, nc.suggested_value) == (
        "arb.front",
        "decrease",
        2.0,
        18.0,
    )
    assert sa.alternatives and sa.alternatives[0].setting != "arb.front"


def test_verdict_with_several_changes_is_not_attributed() -> None:
    before = session("understeer")
    changes = [TuneChange("arb.front", 20.0, 18.0), TuneChange("brake.balance", 52.0, 50.0)]
    sa = analyze_session(lap_analyses("none"), _ctx(before, changes))
    v = sa.verdict_on_last_change
    assert v is not None and len(v.changes) == 2
    assert "can't be attributed" in v.text
    assert "Brake → Braking Balance: 52 → 50" in v.text
    assert sa.next_change is None  # no revert for a combined change


def test_verdict_without_recorded_change_still_compares_lap_times() -> None:
    before = session("understeer")
    sa = analyze_session(lap_analyses("none"), _ctx(before))
    v = sa.verdict_on_last_change
    assert v is not None and v.result == "no-change-recorded" and v.changes == ()
    assert v.text.startswith("No tune change was recorded")
    assert v.lap_time_delta is not None and v.lap_time_delta < 0


def test_verdict_no_clear_effect() -> None:
    before = session("none")
    change = TuneChange("damping.rebound_front", 8.0, 8.5)
    sa = analyze_session(lap_analyses("none"), _ctx(before, [change]))
    v = sa.verdict_on_last_change
    assert v is not None and v.result == "no-clear-effect"
    assert "within lap-to-lap noise" in v.text


def test_a_change_that_helped_is_not_undone_next() -> None:
    from pitwall.analysis import Finding, Verdict
    from pitwall.analysis.session import _choose

    oversteer = Finding("mid-oversteer", "Oversteer", 0.8, 0.9, "Rear slides", consistency=1.0)
    nc, _ = _choose([oversteer], "RWD", "imperial", {}, None, None)
    assert nc is not None and (nc.setting, nc.direction) == ("arb.rear", "decrease")

    helped = Verdict((TuneChange("arb.rear", 20.0, 22.0),), "helped", -0.4, {}, "Helped")
    nc, _ = _choose([oversteer], "RWD", "imperial", {}, helped, None)
    assert nc is not None and (nc.setting, nc.direction) == ("arb.front", "increase")


def test_session_to_dict_is_json_ready() -> None:
    data = json.loads(json.dumps(session("wheelspin").to_dict()))
    assert set(data) == {
        "laps_analyzed",
        "consistency",
        "findings",
        "next_change",
        "alternatives",
        "verdict_on_last_change",
        "limits",
    }
    rec = data["next_change"]
    assert set(rec) >= {
        "id",
        "finding_id",
        "setting",
        "section",
        "label",
        "axle",
        "direction",
        "step",
        "step_unit",
        "suggested_value",
        "text",
        "reason",
        "detail",
        "confidence",
        "priority",
    }
    assert rec["text"] == "Differential → Acceleration (Rear): −5%"
    assert rec["section"] == "Differential" and rec["axle"] == "Rear" and rec["step_unit"] == "%"
    assert set(data["findings"][0]) >= {"id", "title", "severity", "evidence", "detail", "where"}
