"""Imperial/metric conversion of baseline values."""

from __future__ import annotations

import pytest

from pitwall.baselines import baseline, categories
from pitwall.baselines.units import convert, to_imperial, to_metric


@pytest.mark.parametrize(
    "value,unit,metric",
    [
        (29.0, "psi", 2.0),
        (14.5, "psi", 1.0),
        (32.0, "psi", 2.21),
        (500.0, "lb/in", 8.93),
        (1000.0, "lb/in", 17.86),
        (4.0, "in", 10.2),
        (-0.5, "in", -1.3),
        (100.0, "lb", 45.0),
        (18.0, "", 18.0),
        (-1.5, "°", -1.5),
        (55.0, "%", 55.0),
    ],
)
def test_to_metric(value, unit, metric):
    assert to_metric(value, unit) == pytest.approx(metric)


@pytest.mark.parametrize(
    "value,unit,imperial",
    [(2.0, "bar", 29.0), (8.93, "kgf/mm", 500.0), (10.0, "cm", 3.9), (45.0, "kgf", 99.0)],
)
def test_to_imperial(value, unit, imperial):
    assert to_imperial(value, unit) == pytest.approx(imperial)


def test_round_trip_pressure():
    # Bar is shown with two decimals, about 0.15 psi of resolution.
    for psi in (26.0, 28.5, 30.0, 33.5):
        assert to_imperial(to_metric(psi, "psi"), "bar") == pytest.approx(psi, abs=0.15)


def test_convert_imperial_keeps_value():
    assert convert(29.04, "psi", "imperial") == 29.0
    assert convert(-1.25, "°", "imperial") == -1.25


@pytest.mark.parametrize("cid", [c.id for c in categories()])
def test_baseline_metric_matches_imperial(cid):
    imp = {s.key: s for s in baseline(cid, "imperial").settings}
    met = {s.key: s for s in baseline(cid, "metric").settings}
    assert imp.keys() == met.keys()
    for key, i in imp.items():
        m = met[key]
        assert (i.relative, i.note, i.basis) == (m.relative, m.note, m.basis)
        if key.startswith("tires.pressure"):
            assert (i.unit, m.unit) == ("psi", "bar")
            assert m.value == pytest.approx(i.value / 14.5038, abs=0.006)
            assert m.range[0] == pytest.approx(i.range[0] / 14.5038, abs=0.006)
        elif key.startswith("springs.ride_height") or key.startswith("geometry.roll_center"):
            assert (i.unit, m.unit) == ("in", "cm")
            if i.value is not None:
                assert m.value == pytest.approx(i.value * 2.54, abs=0.06)
        elif key in ("springs.front", "springs.rear"):
            assert (i.unit, m.unit) == ("lb/in", "kgf/mm")
        else:
            assert i.value == m.value and i.range == m.range


def test_unknown_unit_system_rejected():
    with pytest.raises(ValueError):
        baseline(categories()[0].id, "furlongs")


def test_unknown_category_rejected():
    with pytest.raises(KeyError):
        baseline("no_such_category")
