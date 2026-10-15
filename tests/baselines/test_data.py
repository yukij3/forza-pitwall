"""Schema and plausibility checks for the bundled baseline data."""

from __future__ import annotations

import re

import pytest

from pitwall.baselines import baseline, categories
from pitwall.baselines.catalog import BASES, DRIVETRAINS, raw_cars, raw_categories
from pitwall.tune.settings import BY_KEY, SETTINGS

DATA = raw_categories()
CATS = DATA["categories"]
CAT_IDS = [c["id"] for c in CATS]
CLASSES = ("E", "D", "C", "B", "A", "S", "R", "P", "X")

# In-game slider limits in Forza Motorsport (2023), imperial units. Settings
# whose scale differs per car (springs, ride height, aero, final drive) never
# carry absolute values, so they are not listed.
GAME_LIMITS: dict[str, tuple[float, float]] = {
    "tires.pressure_front": (15.0, 55.0),
    "tires.pressure_rear": (15.0, 55.0),
    "alignment.camber_front": (-5.0, 5.0),
    "alignment.camber_rear": (-5.0, 5.0),
    "alignment.toe_front": (-5.0, 5.0),
    "alignment.toe_rear": (-5.0, 5.0),
    "alignment.caster": (1.0, 7.0),
    "arb.front": (1.0, 65.0),
    "arb.rear": (1.0, 65.0),
    "damping.rebound_front": (1.0, 20.0),
    "damping.rebound_rear": (1.0, 20.0),
    "damping.bump_front": (1.0, 20.0),
    "damping.bump_rear": (1.0, 20.0),
    "geometry.roll_center_front": (-5.0, 5.0),
    "geometry.roll_center_rear": (-5.0, 5.0),
    "brake.balance": (0.0, 100.0),
    "brake.pressure": (0.0, 200.0),
    "diff.accel_front": (0.0, 100.0),
    "diff.decel_front": (0.0, 100.0),
    "diff.accel_rear": (0.0, 100.0),
    "diff.decel_rear": (0.0, 100.0),
    "diff.center_balance": (0.0, 100.0),
}
# Tighter "is this a sane starting point" bounds for road and race cars alike.
PLAUSIBLE: dict[str, tuple[float, float]] = {
    "tires.pressure_front": (20.0, 40.0),
    "tires.pressure_rear": (20.0, 40.0),
    "alignment.camber_front": (-4.0, 0.0),
    "alignment.camber_rear": (-3.5, 0.0),
    "alignment.toe_front": (-0.5, 0.5),
    "alignment.toe_rear": (-0.5, 0.5),
    "alignment.caster": (4.0, 7.0),
    "brake.balance": (40.0, 60.0),
    "brake.pressure": (70.0, 150.0),
}
# Settings whose in-game range differs per car: no absolute value allowed.
CAR_SPECIFIC = {
    "springs.front",
    "springs.rear",
    "springs.ride_height_front",
    "springs.ride_height_rear",
    "aero.front",
    "aero.rear",
    "gearing.final_drive",
}


def all_entries():
    """(where, key, entry) for every setting entry in the data file."""
    layers = [("common", DATA["common"])] + [(c["id"], c) for c in CATS]
    for name, layer in layers:
        for key, entry in layer.get("settings", {}).items():
            yield f"{name}.settings", key, entry
        for dt, block in layer.get("by_drivetrain", {}).items():
            for key, entry in block.items():
                yield f"{name}.by_drivetrain.{dt}", key, entry


def test_top_level_shape():
    assert DATA["version"] == 1
    assert set(DATA) >= {"version", "divisions", "common", "categories", "fallback"}
    assert len(CATS) >= 10
    assert len(set(CAT_IDS)) == len(CAT_IDS)
    for cid in CAT_IDS:
        assert re.fullmatch(r"[a-z0-9_]+", cid)


@pytest.mark.parametrize("cat", CATS, ids=CAT_IDS)
def test_category_shape(cat):
    assert set(cat) >= {
        "id",
        "name",
        "description",
        "divisions",
        "drivetrains",
        "confidence",
        "settings",
        "by_drivetrain",
        "notes",
        "sources",
    }
    assert cat["name"] and cat["description"]
    assert cat["confidence"] in ("low", "medium")  # never high: starting points only
    assert cat["divisions"], "every category covers at least one in-game division"
    assert set(cat["divisions"]) <= set(DATA["divisions"])
    assert cat["drivetrains"] and set(cat["drivetrains"]) <= set(DRIVETRAINS)
    assert set(cat["by_drivetrain"]) <= set(DRIVETRAINS)
    assert cat["sources"], "every category cites at least one source"
    for src in cat["sources"]:
        assert src["title"] and re.match(r"https?://", src["url"]), src
        assert src.get("used_for"), src


def test_divisions_covered_and_unambiguous():
    covered = {d for c in CATS for d in c["divisions"]}
    assert covered == set(DATA["divisions"]), "every FM2023 division belongs to a category"
    for division in DATA["divisions"]:
        for dt in DRIVETRAINS:
            owners = [
                c["id"] for c in CATS if division in c["divisions"] and dt in c["drivetrains"]
            ]
            assert len(owners) <= 1, (division, dt, owners)


def test_fallback_table_complete():
    fb = DATA["fallback"]
    assert set(fb) == set(DRIVETRAINS)
    for dt in DRIVETRAINS:
        assert set(fb[dt]) == set(CLASSES), dt
        for cid in fb[dt].values():
            assert cid in CAT_IDS


@pytest.mark.parametrize("where,key,entry", list(all_entries()), ids=lambda v: str(v)[:40])
def test_entry_shape(where, key, entry):
    assert key in BY_KEY, f"{where}: unknown setting {key}"
    assert entry.get("basis") in BASES, f"{where}.{key}: basis"
    assert set(entry) <= {"value", "range", "position", "position_range", "note", "basis"}
    assert any(k in entry for k in ("value", "position", "note")), f"{where}.{key}: empty"
    if key in CAR_SPECIFIC:
        assert "value" not in entry and "range" not in entry, f"{where}.{key}: car-specific scale"
        assert entry.get("note"), f"{where}.{key}: needs a rule"
    if "range" in entry:
        lo, hi = entry["range"]
        assert lo <= hi
        assert "value" in entry and lo <= entry["value"] <= hi, f"{where}.{key}"
    if "value" in entry and key in GAME_LIMITS:
        lo, hi = GAME_LIMITS[key]
        values = [entry["value"], *entry.get("range", [])]
        assert all(lo <= v <= hi for v in values), f"{where}.{key}: outside game limits"
    if "value" in entry and key in PLAUSIBLE:
        lo, hi = PLAUSIBLE[key]
        assert lo <= entry["value"] <= hi, f"{where}.{key}: implausible starting value"
    if "position" in entry:
        assert 0.0 <= entry["position"] <= 1.0
        if "position_range" in entry:
            plo, phi = entry["position_range"]
            assert 0.0 <= plo <= entry["position"] <= phi <= 1.0


def test_differential_only_per_drivetrain():
    """Diff values live under by_drivetrain and only where that drivetrain has them."""
    layers = [("common", DATA["common"])] + [(c["id"], c) for c in CATS]
    for name, layer in layers:
        for key in layer.get("settings", {}):
            assert not key.startswith("diff."), f"{name}: {key} must be per drivetrain"
        for dt, block in layer.get("by_drivetrain", {}).items():
            for key in block:
                assert dt in BY_KEY[key].drivetrains, f"{name}.{dt}: {key} doesn't exist for {dt}"


def test_own_drivetrains_have_own_diff_values():
    for cat in CATS:
        for dt in cat["drivetrains"]:
            keys = set(cat["by_drivetrain"].get(dt, {}))
            needed = {s.key for s in SETTINGS if s.key.startswith("diff.") and dt in s.drivetrains}
            assert needed <= keys, (cat["id"], dt, needed - keys)


@pytest.mark.parametrize("cid", CAT_IDS)
@pytest.mark.parametrize("dt", DRIVETRAINS)
def test_baseline_complete_and_drivetrain_safe(cid, dt):
    result = baseline(cid, "imperial", dt)
    keys = [s.key for s in result.settings]
    expected = [s.key for s in SETTINGS if dt in s.drivetrains]
    assert keys == expected, "every applicable setting, in menu order, nothing else"
    for s in result.settings:
        assert dt in BY_KEY[s.key].drivetrains
        assert s.value is not None or s.relative or s.note, s.key
        if s.range is not None:
            assert s.value is not None and s.range[0] <= s.value <= s.range[1]


def test_baseline_values_reflect_drivetrain_logic():
    """Spot checks that the numbers follow basic setup logic."""
    for cid in CAT_IDS:
        b = {s.key: s for s in baseline(cid, "imperial", "AWD").settings}
        # AWD: more lock on the rear than the front under power, rear-biased torque.
        assert b["diff.accel_rear"].value >= b["diff.accel_front"].value, cid
        assert b["diff.center_balance"].value >= 50, cid
        for s in b.values():
            if s.key.startswith("damping.bump"):
                rebound = b[s.key.replace("bump", "rebound")].value
                assert s.value <= rebound, f"{cid}: bump stiffer than rebound"


def test_categories_api_matches_data():
    assert [c.id for c in categories()] == CAT_IDS


def test_cars_file_shape():
    cars = raw_cars()["cars"]
    ordinals = [c["ordinal"] for c in cars]
    assert len(set(ordinals)) == len(ordinals)
    for car in cars:
        assert isinstance(car["ordinal"], int) and car["name"]
        if car.get("division") is not None:
            assert car["division"] in DATA["divisions"], car
        if car.get("category") is not None:
            assert car["category"] in CAT_IDS, car
