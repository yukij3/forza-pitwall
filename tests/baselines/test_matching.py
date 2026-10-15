"""Car identification and category matching."""

from __future__ import annotations

import pytest

from pitwall.baselines import baseline, car_info, categories, match
from pitwall.baselines.catalog import raw_cars
from pitwall.baselines.matching import class_letter, drivetrain_name

FWD, RWD, AWD = 0, 1, 2
CARS = raw_cars()["cars"]
LOLA = next((c for c in CARS if "Lola B12/80" in c["name"]), None)


def test_lola_by_ordinal_or_class():
    """The Mazda #70 Lola B12/80 (PI 949, RWD) is an LMP2 car."""
    if LOLA is not None:
        m = match(LOLA["ordinal"], 949, 7, RWD)
        assert m.category_id == "lmp2"
        assert m.how in ("ordinal", "division")
        assert m.confidence == "high"
        assert m.car.name == LOLA["name"] and m.car.division == "Forza P2"
    m = match(None, 949, 7, RWD)
    assert m.category_id == "lmp2"
    assert (m.how, m.confidence, m.car) == ("class_drivetrain", "low", None)


@pytest.mark.parametrize(
    "pi,dt,expected",
    [
        (949, RWD, "lmp2"),
        (980, AWD, "lmp1_hypercar"),
        (820, RWD, "gt3_gte"),
        (700, FWD, "touring"),
        (450, FWD, "road_fwd"),
        (350, RWD, "road_rwd"),
        (550, AWD, "road_awd"),
        (650, RWD, "sports_muscle"),
        (780, RWD, "supercar"),
        (780, AWD, "supercar"),
    ],
)
def test_class_drivetrain_fallback(pi, dt, expected):
    m = match(None, pi, None, dt)
    assert (m.category_id, m.how, m.confidence) == (expected, "class_drivetrain", "low")


def test_unknown_ordinal_falls_back_to_class():
    m = match(-12345, 949, None, RWD)
    assert m.category_id == "lmp2" and m.how == "class_drivetrain" and m.car is None


def test_class_index_used_when_pi_missing():
    assert class_letter(None, 7) == "P"
    assert class_letter(949, 3) == "P"  # PI wins over the class index
    assert match(None, None, 7, RWD).category_id == "lmp2"


def test_unknown_drivetrain_assumes_rwd():
    assert match(None, 949, None, None).category_id == "lmp2"
    assert match(None, 949, None, 9).category_id == "lmp2"


def test_nothing_known_returns_none():
    assert match(None, None, None, None) is None
    assert match(None, None, None, RWD) is None
    assert match(None, 50, 42, RWD) is None


@pytest.mark.parametrize("pi", [100, 300, 301, 500, 600, 700, 800, 900, 901, 998, 999])
@pytest.mark.parametrize("dt", [FWD, RWD, AWD])
def test_every_class_and_drivetrain_resolves(pi, dt):
    m = match(None, pi, None, dt)
    assert m is not None and m.category_id in {c.id for c in categories()}


def test_drivetrain_names():
    assert [drivetrain_name(v) for v in (0, 1, 2, 3, None, True)] == [
        "FWD",
        "RWD",
        "AWD",
        None,
        None,
        None,
    ]
    assert drivetrain_name("awd") == "AWD"


@pytest.mark.skipif(not CARS, reason="no car list bundled")
def test_every_listed_car_matches_its_division():
    by_id = {c.id: c for c in categories()}
    for car in CARS:
        info = car_info(car["ordinal"])
        assert info is not None and info.name == car["name"]
        m = match(car["ordinal"], None, None, None)
        if car.get("division") or car.get("category"):
            assert m is not None and m.how in ("ordinal", "division"), car
            if m.how == "division":
                assert car["division"] in by_id[m.category_id].divisions


@pytest.mark.skipif(not CARS, reason="no car list bundled")
def test_division_with_swapped_drivetrain_is_medium():
    gt3 = next(c for c in CARS if c.get("division") == "Forza GT3")
    m = match(gt3["ordinal"], 830, None, AWD)
    assert (m.category_id, m.how, m.confidence) == ("gt3_gte", "division", "medium")
    b = baseline(m.category_id, drivetrain=AWD)
    assert b.drivetrain == "AWD"
    assert "diff.center_balance" in {s.key for s in b.settings}


@pytest.mark.skipif(not CARS, reason="no car list bundled")
def test_division_spanning_categories_needs_drivetrain():
    """Modern Hot Hatch holds FWD, AWD and RWD cars: no drivetrain, no high confidence."""
    hatch = next(c for c in CARS if c.get("division") == "Modern Hot Hatch")
    assert match(hatch["ordinal"], None, None, None).confidence == "medium"
    assert match(hatch["ordinal"], None, None, FWD).category_id == "road_fwd"
    assert match(hatch["ordinal"], None, None, AWD).category_id == "road_awd"
    assert match(hatch["ordinal"], None, None, AWD).confidence == "high"
    gt3 = next(c for c in CARS if c.get("division") == "Forza GT3")
    assert match(gt3["ordinal"], None, None, None).confidence == "high"


def test_car_info_unknown():
    assert car_info(-1) is None


def test_to_dict_shapes():
    m = match(None, 949, None, RWD)
    assert m.to_dict() == {
        "category_id": "lmp2",
        "how": "class_drivetrain",
        "confidence": "low",
        "car": None,
    }
    cat = categories()[0].to_dict()
    assert set(cat) == {"id", "name", "description", "divisions", "drivetrains"}
    b = baseline("lmp2", "metric").to_dict()
    assert set(b) >= {"category", "unit_system", "settings", "notes", "sources", "confidence"}
    assert b["unit_system"] == "metric" and b["confidence"] in ("low", "medium")
    assert b["category"]["id"] == "lmp2"
    s = b["settings"][0]
    assert set(s) >= {"key", "section", "label", "axle", "value", "range", "unit", "relative"}
    assert set(s) >= {"note"}
    assert all(set(src) >= {"title", "url"} for src in b["sources"])
    arb = next(x for x in b["settings"] if x["key"] == "arb.front")
    assert (arb["section"], arb["label"], arb["axle"]) == (
        "Anti-roll Bars",
        "Anti-roll Bars",
        "Front",
    )
