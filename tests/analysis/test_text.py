"""UI text: one compact line per finding and recommendation, sentences only in ``detail``."""

from __future__ import annotations

import re

import pytest

from pitwall.analysis import LiveAnalyzer
from pitwall.analysis.synthetic import ISSUES

from .data import lap_analyses, laps, session

MAX_LINE = 64  # "about 60 characters"
MAX_VALUE = 24


def assert_compact(line: str) -> None:
    assert line and len(line) <= MAX_LINE, line
    assert not re.search(r"\.(\s|$)", line), line  # no sentences
    assert ";" not in line and "(" not in line, line


@pytest.mark.parametrize("issue", ISSUES)
def test_lap_findings_and_recommendations_are_one_compact_line(issue: str) -> None:
    for la in lap_analyses(issue):
        by_id = {f.id: f for f in la.findings}
        for f in la.findings:
            assert_compact(f.evidence)
            assert f.detail and len(f.detail) > len(f.evidence)
        for r in la.recommendations:
            assert r.reason == by_id[r.finding_id].evidence
            assert r.detail and r.detail.endswith(".")
            assert r.detail.startswith(by_id[r.finding_id].detail.rstrip("."))


@pytest.mark.parametrize("issue", ISSUES)
def test_session_lines_carry_the_lap_count_as_a_token(issue: str) -> None:
    sa = session(issue)
    for f in sa.findings:
        assert_compact(f.evidence)
        assert f.evidence.endswith(f"· {f.laps}/{sa.laps_analyzed} laps")
        assert f.detail and f.detail.endswith(f"(seen in {f.laps} of {sa.laps_analyzed} laps)")
    for r in [sa.next_change, *sa.alternatives]:
        if r is not None:
            assert_compact(r.reason)
            assert r.detail


@pytest.mark.parametrize("issue", ["none", *ISSUES])
def test_board_texts_stay_short(issue: str) -> None:
    live = LiveAnalyzer(1)
    for lap in laps(issue)[:2]:
        for frame in lap:
            live.push(frame)
    for item in live.snapshot().items:
        assert len(item.value_text) <= MAX_VALUE, item.value_text
        assert len(item.target_text) <= MAX_VALUE, item.target_text
        if item.recommendation is not None:
            assert_compact(item.recommendation.reason)


def test_to_dict_has_detail() -> None:
    lap = lap_analyses("understeer")[0].to_dict()
    assert lap["findings"][0]["detail"]
    assert lap["recommendations"][0]["detail"]
    assert "·" in lap["recommendations"][0]["reason"]
