"""Plain-English notes on what Data Out can't see."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .results import Finding, Recommendation

ARROW = "→"

LIMIT_TIRES = (
    f"Tire pressure and temperature across the tread (camber) aren't in Data Out: check "
    f"Telemetry {ARROW} Heat in game before changing pressure or camber."
)
LIMIT_TUNE = "Data Out doesn't include the tune, so changes are steps, not target values."
LIMIT_VALIDITY = (
    "Data Out doesn't report track-limit penalties: laps the game invalidated may still count."
)
LIMIT_GEARS = (
    "Data Out doesn't say how many gears the car has: gearing advice is based on rpm at the "
    "end of the longest straight."
)
LIMIT_AERO = (
    "Aero advice assumes the car has adjustable aero; if the Aero section is locked, use the "
    "alternative."
)
LIMIT_NO_DATA = "No frames with the race running, so there is nothing to analyse."
LIMIT_NO_LAPS = "No valid flying laps in this session yet, so there is nothing to diagnose."


def few_laps(n: int) -> str:
    return (
        f"Only {n} valid flying lap{'s' if n != 1 else ''} so far: treat the findings as "
        f"provisional and drive 3–5 clean laps."
    )


def _common(
    tune_values: Mapping[str, float],
    findings: Iterable[Finding],
    recs: Iterable[Recommendation | None],
) -> list[str]:
    out = [LIMIT_TIRES]
    if not tune_values:
        out.append(LIMIT_TUNE)
    ids = {f.id for f in findings}
    if ids & {"gearing-short", "gearing-long"}:
        out.append(LIMIT_GEARS)
    if any(r is not None and r.setting.startswith("aero.") for r in recs) and not any(
        k.startswith("aero.") for k in tune_values
    ):
        out.append(LIMIT_AERO)
    return out


def lap_limits(
    tune_values: Mapping[str, float],
    findings: Iterable[Finding],
    recs: Iterable[Recommendation | None],
    frames: int,
) -> list[str]:
    if frames == 0:
        return [LIMIT_NO_DATA]
    return _common(tune_values, findings, recs)


def session_limits(
    tune_values: Mapping[str, float],
    laps_analyzed: int,
    findings: Iterable[Finding],
    recs: Iterable[Recommendation | None],
) -> list[str]:
    if laps_analyzed == 0:
        return [LIMIT_NO_LAPS, LIMIT_TIRES, LIMIT_VALIDITY]
    out = _common(tune_values, findings, recs)
    out.append(LIMIT_VALIDITY)
    if laps_analyzed < 3:
        out.append(few_laps(laps_analyzed))
    return out
