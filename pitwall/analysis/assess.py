"""Turns event records into rated board items.

One :class:`Assessment` per board item: a value, how far it sits outside its OK
band (the band score), the evidence behind it and the finding (rulebook
symptom) it points to. The per-lap analysis turns assessments into findings;
the live board turns them into coloured items with hysteresis. Both therefore
judge a lap and a rolling window with identical rules.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from statistics import median

from .records import (
    DRIVEN_AXLES,
    BottomingEvent,
    BrakeRecord,
    CornerRecord,
    StraightRecord,
)
from .results import BoardItem, Finding, Recommendation, Where
from .rules import FINDING_TITLES, MINUS, applicable_changes, build_recommendation, reason_text
from .thresholds import (
    BANDS,
    GEAR_SETTLED_S,
    GEARING_LONG_CONFIDENCE,
    GEARING_PEAK_BAD,
    GEARING_PEAK_OK,
    GEARING_SHORT_CONFIDENCE,
    LIMITER_BAD_S,
    LIMITER_OK_S,
    LONG_STRAIGHT_MIN_M,
    MIN_EVENTS_FOR_WARN,
    PHASE_EVENT_MIN_S,
    PINNED_CONFIDENCE_FACTOR,
    PINNED_SHARE_CAVEAT,
    STATUS_HYSTERESIS,
    TIRE_COLD_C,
    TIRE_CONFIDENCE,
    TIRE_HOT_C,
    TIRE_VERY_COLD_C,
    TIRE_VERY_HOT_C,
    Bands,
)

# (id, group, title) in display order.
ITEMS: tuple[tuple[str, str, str], ...] = (
    ("entry_balance", "Balance", "Corner entry"),
    ("mid_balance_low", "Balance", "Mid-corner, slow corners"),
    ("mid_balance_high", "Balance", "Mid-corner, fast corners"),
    ("exit_balance", "Balance", "Corner exit"),
    ("exit_wheelspin", "Traction", "Wheelspin on exit"),
    ("lockups_front", "Braking", "Front lockups"),
    ("lockups_rear", "Braking", "Rear lockups"),
    ("braking_stability", "Braking", "Stability under braking"),
    ("bottoming_front", "Suspension", "Bottoming, front"),
    ("bottoming_rear", "Suspension", "Bottoming, rear"),
    ("gearing", "Gearing", "Gearing"),
    ("tire_temps", "Tires", "Tire temperature, front vs rear"),
)
_META = {i: (g, t) for i, g, t in ITEMS}
_BELOW_WARN = -(STATUS_HYSTERESIS + 0.01)  # score used when too few events to warn


@dataclass(slots=True)
class Evidence:
    """Everything one assessment run looks at (one lap, or the live window)."""

    corners: Sequence[CornerRecord]
    brakes: Sequence[BrakeRecord]
    straights: Sequence[StraightRecord]
    bottoming: Sequence[BottomingEvent]
    tire_avg_c: tuple[float, float, float, float] | None
    tire_seconds: float
    top_gear: int
    drivetrain: str
    corner_at: Callable[[float], int | None] = field(default=lambda _d: None)
    peak_power_rpm: float | None = None  # fraction of max rpm, once proven


@dataclass(slots=True)
class Assessment:
    item: str
    value: float | None
    value_text: str
    target_text: str
    samples: int
    score: float  # band score: <= 0 inside the OK band, 0.5 at the bad edge
    confidence: float
    finding_id: str | None = None
    evidence: str = ""  # one compact line: "Understeer +0.64 · 4 slow corners"
    where: list[Where] = field(default_factory=list)
    axle: str | None = None
    detail: str = ""  # the same in sentences, for a tooltip

    @property
    def min_samples(self) -> int:
        return BANDS[self.item].min_samples

    @property
    def collecting(self) -> bool:
        return self.samples < self.min_samples

    @property
    def severity(self) -> float:
        if self.collecting:
            return 0.0
        return max(0.0, min(1.0, self.score))


# --- Band maths ---------------------------------------------------------------------------
def band_score(value: float, b: Bands) -> float:
    """0 at an OK edge, 0.5 at the bad edge, up to 1; negative inside OK."""
    if b.ok_high is not None and value > b.ok_high:
        span = (b.bad_high - b.ok_high) if b.bad_high is not None else 1.0
        return min(1.0, 0.5 * (value - b.ok_high) / span)
    if b.ok_low is not None and value < b.ok_low:
        span = (b.ok_low - b.bad_low) if b.bad_low is not None else 1.0
        return min(1.0, 0.5 * (b.ok_low - value) / span)
    inside = []
    if b.ok_high is not None and b.bad_high is not None:
        inside.append(0.5 * (b.ok_high - value) / (b.bad_high - b.ok_high))
    if b.ok_low is not None and b.bad_low is not None:
        inside.append(0.5 * (value - b.ok_low) / (b.ok_low - b.bad_low))
    return -min(inside) if inside else -0.5


def status_for(a: Assessment, previous: str | None = None) -> str:
    """ok / warn / bad / collecting, with hysteresis against ``previous``."""
    if a.collecting:
        return "collecting"
    s, h = a.score, STATUS_HYSTERESIS
    if previous == "ok":
        return "bad" if s > 0.5 + h else ("warn" if s > h else "ok")
    if previous == "warn":
        return "bad" if s > 0.5 + h else ("ok" if s < -h else "warn")
    if previous == "bad":
        return "ok" if s < -h else ("warn" if s < 0.5 - h else "bad")
    return "ok" if s <= 0 else ("warn" if s <= 0.5 else "bad")


def _signed(x: float, digits: int = 2) -> str:
    text = f"{abs(x):.{digits}f}"
    return f"+{text}" if x >= 0 else f"{MINUS}{text}"


def _balance_target(b: Bands) -> str:
    return f"{_signed(b.ok_low)} … {_signed(b.ok_high)}"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _line(*parts: str) -> str:
    """Compact evidence: the non-empty parts joined with a middle dot."""
    return " · ".join(p for p in parts if p)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


# --- Balance --------------------------------------------------------------------------------
_PHASE_WORDS = {"entry": "entry", "mid": "mid-corner", "exit": "exit"}


def _balance(
    ev: Evidence,
    item: str,
    phase: str,
    select: Callable[[CornerRecord], bool],
    ids: tuple[str, str],
    corner_word: str,
) -> Assessment:
    bands = BANDS[item]
    target = _balance_target(bands)
    cs = [
        c for c in ev.corners if not c.partial and select(c) and c.phase(phase).balance is not None
    ]
    n = len(cs)
    if n == 0:
        return Assessment(item, None, "No corners yet", target, 0, 0.0, 0.0)
    vals = [c.phase(phase).balance for c in cs]
    v = median(vals)
    score = band_score(v, bands)
    under = v > 0
    if abs(v) < 0.02:
        value_text = "Neutral"
    else:
        value_text = f"{'Understeer' if under else 'Oversteer'} {abs(v):.2f}"

    sign_share = sum(1 for x in vals if (x > 0) == under) / n
    if under:
        flagged = [c for c in cs if c.phase(phase).understeer_s >= PHASE_EVENT_MIN_S]
    else:
        flagged = [c for c in cs if c.phase(phase).oversteer_s >= PHASE_EVENT_MIN_S]
    yaws = [c.phase(phase).yaw for c in cs if c.phase(phase).yaw is not None]
    yaw_agree = sum(1 for y in yaws if (y > 0) == under) / len(yaws) if yaws else 0.5
    confidence = (
        0.3 + 0.2 * sign_share + 0.2 * yaw_agree + 0.2 * len(flagged) / n + 0.1 * min(1.0, n / 8)
    )
    seconds = sum(c.phase(phase).seconds for c in cs)
    pinned = sum(c.phase(phase).pinned_s for c in cs) / seconds if seconds > 0 else 0.0

    word = "understeer" if under else "oversteer"
    axle = "front" if under else "rear"
    detail = (
        f"{_PHASE_WORDS[phase].capitalize()} balance {_signed(v)} ({word}) over "
        f"{_plural(n, corner_word)}; {axle} tires past the grip limit in {len(flagged)} of {n}"
    )
    kind = corner_word.removesuffix("corner").strip()  # "slow", "fast" or "" (all corners)
    where_text = f"{kind} corners" if kind else ""
    caveat = f"{axle} slides {len(flagged)}/{n}"  # the count is in the fraction
    if not under:
        cs_count = sum(1 for c in cs if c.phase(phase).countersteer_s >= 0.1)
        if cs_count:
            detail += f", counter-steer in {cs_count}"
    elif pinned >= PINNED_SHARE_CAVEAT:
        confidence *= PINNED_CONFIDENCE_FACTOR
        where_text = _plural(n, corner_word)
        caveat = f"full lock {pinned:.0%}"
        detail += (
            f"; steering at full lock {pinned:.0%} of the time, so part of the front slip "
            "is the steering input, not the set-up"
        )
    evidence = _line(f"{word.capitalize()} {_signed(v)}", where_text, caveat)
    shown = flagged or sorted(cs, key=lambda c: -abs(c.phase(phase).balance or 0.0))[:3]
    where = [Where(c.apex_dist, c.number or None) for c in shown]
    return Assessment(
        item,
        v,
        value_text,
        target,
        n,
        score,
        min(0.95, confidence),
        ids[0] if under else ids[1],
        evidence,
        where,
        axle,
        detail,
    )


# --- Event-rate items -------------------------------------------------------------------------
def _rate(item: str, events: int, total: int, unit: str) -> tuple[float, float, str]:
    rate = events / total if total else 0.0
    score = band_score(rate, BANDS[item])
    if events < MIN_EVENTS_FOR_WARN:
        score = min(score, _BELOW_WARN)
    return rate, score, f"{events}/{total} {unit}"


def _event_confidence(events: int, total: int) -> float:
    return 0.5 + 0.3 * min(1.0, events / 4) + 0.2 * min(1.0, total / 8)


def _wheelspin(ev: Evidence) -> Assessment:
    item = "exit_wheelspin"
    target = "≤ 1 in 10 exits"
    cs = [c for c in ev.corners if not c.partial]
    n = len(cs)
    spins = [c for c in cs if c.spin_axle]
    rate, score, text = _rate(item, len(spins), n, "exits")
    driven = DRIVEN_AXLES.get(ev.drivetrain, ("rear",))
    axle = Counter(c.spin_axle for c in spins).most_common(1)[0][0] if spins else driven[-1]
    evidence = _line(f"{axle.capitalize()} wheelspin", f"{len(spins)}/{n} exits")
    detail = (
        f"Driven {axle} wheels spin (slip ratio above 1.0 under throttle) on {len(spins)} of "
        f"{_plural(n, 'corner exit')}"
    )
    where = [Where(c.spin_dist or c.end_dist, c.number or None) for c in spins]
    return Assessment(
        item,
        rate,
        text,
        target,
        n,
        score,
        _event_confidence(len(spins), n),
        "exit-wheelspin",
        evidence,
        where,
        axle,
        detail,
    )


def _lockups(ev: Evidence, axle: str) -> Assessment:
    item = f"lockups_{axle}"
    target = "≤ 1 in 10 stops"
    bs = [b for b in ev.brakes if not b.partial]
    n = len(bs)
    locked = [b for b in bs if (b.locked_front if axle == "front" else b.locked_rear)]
    rate, score, text = _rate(item, len(locked), n, "stops")
    other = "rear" if axle == "front" else "front"
    other_locked = sum(1 for b in bs if (b.locked_rear if axle == "front" else b.locked_front))
    other_score = band_score(other_locked / n, BANDS[f"lockups_{other}"]) if n else -1.0
    both = score > 0 and other_score > 0 and other_locked >= MIN_EVENTS_FOR_WARN
    evidence = _line(
        f"{axle.capitalize()} lockups",
        f"{len(locked)}/{n} stops",
        f"{other} {other_locked}/{n}" if both else "",
    )
    detail = (
        f"A {axle} wheel stops under braking (for 0.1 s or more) in "
        f"{len(locked)} of {_plural(n, 'braking zone')}"
    )
    if both:
        detail += f"; a {other} wheel stops in {other_locked}"
    where = []
    for b in locked:
        d = b.lock_front_dist if axle == "front" else b.lock_rear_dist
        if d is not None:
            where.append(Where(d, ev.corner_at(b.end_dist)))
    return Assessment(
        item,
        rate,
        text,
        target,
        n,
        score,
        _event_confidence(len(locked), n),
        "lockup-both" if both else f"lockup-{axle}",
        evidence,
        where,
        None if both else axle,
        detail,
    )


def _stability(ev: Evidence) -> Assessment:
    item = "braking_stability"
    target = "≤ 1 in 10 stops"
    bs = [b for b in ev.brakes if not b.partial]
    n = len(bs)
    bad = [b for b in bs if b.unstable]
    rate, score, text = _rate(item, len(bad), n, "stops")
    evidence = _line("Rear slides under braking", f"{len(bad)}/{n} stops")
    detail = (
        f"Rear slides (rear slip angle above the front) while braking in a straight line in "
        f"{len(bad)} of {_plural(n, 'braking zone')}"
    )
    where = [Where(b.unstable_dist, ev.corner_at(b.end_dist)) for b in bad if b.unstable_dist]
    return Assessment(
        item,
        rate,
        text,
        target,
        n,
        score,
        _event_confidence(len(bad), n),
        "braking-instability",
        evidence,
        where,
        "rear",
        detail,
    )


def _bottoming(ev: Evidence, axle: str) -> Assessment:
    item = f"bottoming_{axle}"
    evs = [e for e in ev.bottoming if e.axle == axle]
    k = len(evs)
    n = sum(1 for c in ev.corners if not c.partial)
    score = band_score(float(k), BANDS[item])
    spots = len({round(e.dist / 50.0) for e in evs})
    confidence = 0.5 + 0.1 * min(3, k) + (0.1 if spots >= 2 else 0.0)
    evidence = _line(f"{axle.capitalize()} bottoming", _plural(k, "hit"), _plural(spots, "spot"))
    detail = (
        f"{axle.capitalize()} suspension reached full compression at speed "
        f"{_plural(k, 'time')} at {_plural(spots, 'spot')}"
    )
    where = [Where(e.dist, ev.corner_at(e.dist)) for e in evs]
    return Assessment(
        item,
        float(k),
        _plural(k, "hit"),
        "≤ 1 hit",
        n,
        score,
        confidence,
        f"bottoming-{axle}",
        evidence,
        where,
        axle,
        detail,
    )


# --- Gearing ----------------------------------------------------------------------------------
_PEAK_BANDS = Bands(GEARING_PEAK_OK, None, GEARING_PEAK_BAD, None, 1)


def _gearing(ev: Evidence) -> Assessment:
    item = "gearing"
    peak = ev.peak_power_rpm
    target = "85–98% rpm, no limiter" if peak is None else f"≥ peak power ({peak:.0%}), no limiter"
    sts = [s for s in ev.straights if not s.cut_end and s.length >= LONG_STRAIGHT_MIN_M]
    if not sts:
        return Assessment(item, None, "No long straight yet", target, 0, 0.0, 0.0)
    st = max(sts, key=lambda s: s.length)
    top = max(ev.top_gear, st.max_gear)
    gear = _ordinal(st.end_gear)
    where = [Where(st.end_dist, None)]
    in_top = st.end_gear >= top
    if in_top and st.limiter_s >= LIMITER_OK_S:
        score = min(1.0, 0.5 * (st.limiter_s - LIMITER_OK_S) / (LIMITER_BAD_S - LIMITER_OK_S))
        score = max(score, 0.05)
        evidence = _line(f"Limiter {st.limiter_s:.1f} s", gear, f"{st.length:.0f} m straight")
        detail = (
            f"On the rev limiter for {st.limiter_s:.1f} s in {gear} at the end of the "
            f"{st.length:.0f} m straight"
        )
        return Assessment(
            item,
            st.end_rpm_pct,
            f"Limiter {st.limiter_s:.1f} s · {gear}",
            target,
            len(sts),
            score,
            GEARING_SHORT_CONFIDENCE,
            "gearing-short",
            evidence,
            where,
            detail=detail,
        )
    value_text = f"{gear} · {st.end_rpm_pct:.0%} rpm"
    if in_top and st.gear_time_s >= GEAR_SETTLED_S:
        detail = (
            f"The top gear used ({gear}) only reaches {st.end_rpm_pct:.0%} of max rpm at "
            f"the end of the {st.length:.0f} m straight"
        )
        if peak is None:
            score = band_score(st.end_rpm_pct, BANDS[item])
            evidence = _line(value_text, f"{st.length:.0f} m straight")
        else:
            score = band_score(st.end_rpm_pct / peak, _PEAK_BANDS)
            evidence = _line(value_text, f"peak power {peak:.0%}")
            detail += f"; peak power is at {peak:.0%}"
        return Assessment(
            item,
            st.end_rpm_pct,
            value_text,
            target,
            len(sts),
            score,
            GEARING_LONG_CONFIDENCE,
            "gearing-long" if score > 0 else None,
            evidence,
            where,
            detail=detail,
        )
    return Assessment(item, st.end_rpm_pct, value_text, target, len(sts), -0.5, 0.5)


# --- Tires ------------------------------------------------------------------------------------
def _tires(ev: Evidence) -> Assessment:
    item = "tire_temps"
    target = f"within ±8 °C; {TIRE_COLD_C:.0f}–{TIRE_HOT_C:.0f} °C"
    if ev.tire_avg_c is None:
        return Assessment(item, None, "No data yet", target, 0, 0.0, 0.0)
    fl, fr, rl, rr = ev.tire_avg_c
    front, rear = (fl + fr) / 2, (rl + rr) / 2
    diff = front - rear
    s_diff = band_score(diff, BANDS[item])
    hot_axle, hot = ("front", front) if front >= rear else ("rear", rear)
    cold_axle, cold = ("rear", rear) if front >= rear else ("front", front)
    s_hot = 0.5 * (hot - TIRE_HOT_C) / (TIRE_VERY_HOT_C - TIRE_HOT_C) if hot > TIRE_HOT_C else -1
    s_cold = (
        0.5 * (TIRE_COLD_C - cold) / (TIRE_COLD_C - TIRE_VERY_COLD_C) if cold < TIRE_COLD_C else -1
    )
    score = min(1.0, max(s_diff, s_hot, s_cold))
    finding = None
    if score > 0:
        if s_cold >= max(s_hot, s_diff):
            finding = f"tires-cold-{cold_axle}"
        else:
            finding = f"tires-hot-{hot_axle}"
    axle = finding.rsplit("-", 1)[1] if finding else None
    evidence = _line(f"Front {front:.0f} °C", f"rear {rear:.0f} °C")
    detail = (
        f"Average tire temperature front {front:.0f} °C, rear {rear:.0f} °C "
        f"(one value per tire; pressure isn't in Data Out)"
    )
    value_text = f"Front {_signed(diff, 0)} °C vs rear"
    return Assessment(
        item,
        diff,
        value_text,
        target,
        int(ev.tire_seconds),
        score,
        TIRE_CONFIDENCE,
        finding,
        evidence,
        [],
        axle,
        detail,
    )


# --- Entry point ------------------------------------------------------------------------------
def assess_all(ev: Evidence) -> list[Assessment]:
    def slow(c: CornerRecord) -> bool:
        return c.band == "low"

    def fast(c: CornerRecord) -> bool:
        return c.band == "high"

    def every(_c: CornerRecord) -> bool:
        return True

    return [
        _balance(
            ev, "entry_balance", "entry", every, ("entry-understeer", "entry-oversteer"), "corner"
        ),
        _balance(
            ev, "mid_balance_low", "mid", slow, ("mid-understeer", "mid-oversteer"), "slow corner"
        ),
        _balance(
            ev,
            "mid_balance_high",
            "mid",
            fast,
            ("high-speed-understeer", "high-speed-oversteer"),
            "fast corner",
        ),
        _balance(
            ev, "exit_balance", "exit", every, ("exit-understeer", "exit-oversteer"), "corner"
        ),
        _wheelspin(ev),
        _lockups(ev, "front"),
        _lockups(ev, "rear"),
        _stability(ev),
        _bottoming(ev, "front"),
        _bottoming(ev, "rear"),
        _gearing(ev),
        _tires(ev),
    ]


def finding_from(a: Assessment) -> Finding:
    assert a.finding_id is not None
    return Finding(
        id=a.finding_id,
        title=FINDING_TITLES.get(a.finding_id, a.finding_id),
        severity=a.severity,
        confidence=a.confidence,
        evidence=a.evidence,
        where=tuple(a.where),
        axle=a.axle,
        item=a.item,
        detail=a.detail or None,
    )


def recommend(
    finding_id: str,
    axle: str | None,
    evidence: str,
    confidence: float,
    *,
    drivetrain: str,
    unit_system: str,
    tune_values: dict[str, float] | None,
    priority: int = 1,
    detail: str | None = None,
) -> Recommendation | None:
    """The first applicable rule for a finding, as a Recommendation.

    ``reason`` is the finding's compact evidence line; ``detail`` adds the
    finding's sentences and why the change helps.
    """
    tv = tune_values or {}
    cands = applicable_changes(finding_id, drivetrain, axle, tv, unit_system)
    if not cands:
        return None
    change, prior = cands[0]
    return build_recommendation(
        change,
        finding_id=finding_id,
        reason=evidence,
        detail=reason_text(detail or evidence, change.why),
        confidence=confidence * prior,
        unit_system=unit_system,
        tune_values=tv,
        priority=priority,
    )


def board_item(a: Assessment, status: str, recommendation: Recommendation | None) -> BoardItem:
    group, title = _META[a.item]
    return BoardItem(
        id=a.item,
        group=group,
        title=title,
        status=status,
        value=a.value,
        value_text=a.value_text,
        target_text=a.target_text,
        samples=a.samples,
        severity=a.severity,
        confidence=a.confidence,
        recommendation=recommendation,
    )


def build_board(
    assessments: Sequence[Assessment],
    *,
    drivetrain: str,
    unit_system: str,
    tune_values: dict[str, float] | None,
    previous: dict[str, str] | None = None,
) -> tuple[list[BoardItem], str | None]:
    """Rate every item (with hysteresis if ``previous`` is given) and pick the focus.

    ``previous`` is updated in place with the new statuses.
    """
    items: list[BoardItem] = []
    best: tuple[float, str] | None = None
    for a in assessments:
        prev = previous.get(a.item) if previous is not None else None
        status = status_for(a, prev)
        if previous is not None:
            previous[a.item] = status
        rec = None
        if status in ("warn", "bad") and a.finding_id:
            rec = recommend(
                a.finding_id,
                a.axle,
                a.evidence,
                a.confidence,
                drivetrain=drivetrain,
                unit_system=unit_system,
                tune_values=tune_values,
                detail=a.detail,
            )
        if rec is not None:
            weight = max(a.severity, 0.05) * rec.confidence * (1.5 if status == "bad" else 1.0)
            if best is None or weight > best[0]:
                best = (weight, a.item)
        items.append(board_item(a, status, rec))
    return items, best[1] if best else None
