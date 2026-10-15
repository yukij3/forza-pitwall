"""Session analysis: aggregate valid flying laps, rank one next change, and judge
the last tune change against the previous session."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from statistics import mean, median, stdev
from typing import Any

from pitwall.tune.settings import BY_KEY

from .results import (
    Finding,
    LapAnalysis,
    Recommendation,
    SessionAnalysis,
    SessionContext,
    TuneChange,
    Verdict,
    Where,
    drivetrain_name,
    rnd,
)
from .rules import (
    FINDING_NAMES,
    MINUS,
    RULES,
    Change,
    applicable_changes,
    build_recommendation,
    describe_change,
    reason_text,
)
from .text import session_limits
from .thresholds import (
    CONSISTENT_LAP_CV,
    INCONSISTENT_LAP_CV,
    LAP_TIME_NOISE_MIN_S,
    MIN_ALTERNATIVE_SCORE,
    MIN_NEXT_CHANGE_CONFIDENCE,
    MIN_NEXT_CHANGE_SCORE,
    NEW_ISSUE_SEVERITY,
    TARGET_IMPROVED_ABS,
    TARGET_IMPROVED_REL,
)

_DRIVER_FACTOR = {"consistent": 1.0, "variable": 0.9, "inconsistent": 0.75}
_RESULT_LABEL = {
    "helped": "Helped",
    "hurt": "Made it worse",
    "mixed": "Mixed",
    "no-clear-effect": "No clear effect",
}
_MAX_WHERE = 10

Candidate = tuple[float, Finding, Change, float]  # score, finding, change, adjusted prior


# --- Consistency ------------------------------------------------------------------------
def _consistency(laps: Sequence[LapAnalysis], valid: Sequence[LapAnalysis]) -> dict[str, Any]:
    timed = [lap for lap in valid if lap.lap_time]
    times = [lap.lap_time for lap in timed if lap.lap_time is not None]
    out: dict[str, Any] = {
        "laps_total": len(laps),
        "laps_valid": len(valid),
        "lap_numbers": [lap.lap_number for lap in timed],
        "lap_times": [rnd(t) for t in times],
        "best": None,
        "median": None,
        "mean": None,
        "stdev": None,
        "spread": None,
        "cv": None,
        "rating": None,
    }
    if not times:
        return out
    avg = mean(times)
    sd = stdev(times) if len(times) > 1 else 0.0
    cv = sd / avg if avg else 0.0
    out.update(
        best=rnd(min(times)),
        median=rnd(median(times)),
        mean=rnd(avg),
        stdev=rnd(sd),
        spread=rnd(max(times) - min(times)),
        cv=rnd(cv, 4),
    )
    if len(times) > 1:
        if cv <= CONSISTENT_LAP_CV:
            out["rating"] = "consistent"
        elif cv <= INCONSISTENT_LAP_CV:
            out["rating"] = "variable"
        else:
            out["rating"] = "inconsistent"
    return out


# --- Findings ------------------------------------------------------------------------------
def _merge_where(findings: Sequence[Finding]) -> tuple[Where, ...]:
    points = sorted((w for f in findings for w in f.where), key=lambda w: w.distance)
    merged: list[Where] = []
    for w in points:
        if merged and w.distance - merged[-1].distance < 60.0:
            continue
        merged.append(w)
    return tuple(merged[:_MAX_WHERE])


def _aggregate(valid: Sequence[LapAnalysis], consistency: dict[str, Any]) -> list[Finding]:
    n = len(valid)
    if n == 0:
        return []
    by_id: dict[str, list[Finding]] = defaultdict(list)
    for lap in valid:
        for f in lap.findings:
            by_id[f.id].append(f)
    lap_factor = {1: 0.6, 2: 0.8}.get(n, 1.0)
    driver = _DRIVER_FACTOR.get(consistency.get("rating") or "", 1.0)
    out: list[Finding] = []
    for fid, fs in by_id.items():
        k = len(fs)
        share = k / n
        if n >= 3 and share < 0.3:
            continue  # a one-off, not a property of the car
        top = max(fs, key=lambda f: f.severity)
        axle = Counter(f.axle for f in fs).most_common(1)[0][0]
        conf = mean(f.confidence for f in fs) * lap_factor * (0.5 + 0.5 * share) * driver
        evidence = top.evidence + (f" · {k}/{n} laps" if n > 1 else "")
        detail = (top.detail or top.evidence) + (f" (seen in {k} of {n} laps)" if n > 1 else "")
        out.append(
            Finding(
                id=fid,
                title=top.title,
                severity=median(f.severity for f in fs),
                confidence=min(1.0, conf),
                evidence=evidence,
                where=_merge_where(fs),
                axle=axle,
                item=top.item,
                laps=k,
                consistency=share,
                detail=detail,
            )
        )
    out.sort(key=lambda f: -(f.severity * f.confidence * f.consistency))
    return out


def _weight(f: Finding) -> float:
    return f.severity * f.consistency


# --- Verdict --------------------------------------------------------------------------------
def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def _change_dir(c: TuneChange) -> int:
    if c.from_value is None or c.to_value is None:
        return 0
    return _sign(c.to_value - c.from_value)


def _targets(changes: Sequence[TuneChange], prev: SessionAnalysis) -> list[str]:
    ids: list[str] = []
    for c in changes:
        d = _change_dir(c)
        if prev.next_change is not None and prev.next_change.setting == c.setting:
            ids.append(prev.next_change.finding_id)
        for fid, rule in RULES.items():
            if any(ch.setting == c.setting and (d == 0 or ch.direction == d) for ch in rule):
                ids.append(fid)
    return list(dict.fromkeys(ids))


def _seconds(x: float) -> str:
    text = f"{abs(x):.2f}"
    return f"+{text}" if x >= 0 else f"{MINUS}{text}"


def _verdict(
    consistency: dict[str, Any],
    findings: Sequence[Finding],
    prev: SessionAnalysis,
    changes: tuple[TuneChange, ...],
    unit_system: str,
    tune_values: dict[str, float],
) -> tuple[Verdict, Recommendation | None]:
    cur_med, prev_med = consistency.get("median"), prev.lap_time_median
    delta = cur_med - prev_med if cur_med is not None and prev_med is not None else None
    noise = max(
        LAP_TIME_NOISE_MIN_S, 0.5 * ((consistency.get("stdev") or 0.0) + prev.lap_time_stdev)
    )
    before = {f.id: _weight(f) for f in prev.findings}
    after = {f.id: _weight(f) for f in findings}
    deltas = {
        fid: {
            "before": before.get(fid, 0.0),
            "after": after.get(fid, 0.0),
            "delta": after.get(fid, 0.0) - before.get(fid, 0.0),
        }
        for fid in sorted(set(before) | set(after))
        if max(before.get(fid, 0.0), after.get(fid, 0.0)) >= 0.1
    }
    if delta is None:
        lap_part = "no valid lap times to compare"
    else:
        lap_part = f"{_seconds(delta)} s median lap"
        if abs(delta) < noise:
            lap_part += " (within lap-to-lap noise)"

    if not changes:
        text = f"No tune change was recorded since the previous session: {lap_part}."
        return Verdict((), "no-change-recorded", delta, deltas, text), None

    targets = [t for t in _targets(changes, prev) if before.get(t, 0.0) > 0]
    improved = worsened = False
    parts: list[str] = []
    for t in targets:
        b, a = before[t], after.get(t, 0.0)
        drop = b - a
        if drop >= TARGET_IMPROVED_ABS or (drop >= 0.05 and drop >= TARGET_IMPROVED_REL * b):
            improved = True
        if -drop >= TARGET_IMPROVED_ABS or (-drop >= 0.05 and -drop >= TARGET_IMPROVED_REL * b):
            worsened = True
        name = FINDING_NAMES.get(t, t)
        pct = round(100 * (a - b) / b)
        if a == 0:
            parts.append(f"{name} gone")
        elif abs(pct) < 10:
            parts.append(f"{name} unchanged")
        else:
            parts.append(f"{name} {'down' if pct < 0 else 'up'} {abs(pct)}%")
    new = [
        fid
        for fid, a in after.items()
        if fid not in before and fid not in targets and a >= NEW_ISSUE_SEVERITY
    ]
    parts += [f"new: {FINDING_NAMES.get(fid, fid)}" for fid in new]

    lap_better = delta is not None and delta <= -noise
    lap_worse = delta is not None and delta >= noise
    gain = lap_better or improved
    loss = lap_worse or worsened or bool(new)
    if gain and not loss:
        result = "helped"
    elif gain and loss:
        result = "mixed"
    elif loss:
        result = "hurt"
    else:
        result = "no-clear-effect"

    detail = ", ".join([lap_part, *parts[:3]])
    descs = [describe_change(c.setting, c.from_value, c.to_value) for c in changes]
    if len(changes) == 1:
        text = f"{_RESULT_LABEL[result]}: {detail} ({descs[0]})."
    else:
        text = (
            f"{len(changes)} settings changed at once ({'; '.join(descs)}): {detail}. "
            f"The effect can't be attributed to one of them."
        )
    verdict = Verdict(changes, result, delta, deltas, text)

    revert = None
    c = changes[0]
    if len(changes) == 1 and result == "hurt" and c.setting in BY_KEY and _change_dir(c):
        assert c.from_value is not None and c.to_value is not None
        back = Change(c.setting, -_change_dir(c), 1.0, "undo it")
        slug = c.setting.replace(".", "-").replace("_", "-")
        effect = f"gave {detail}"
        lap_token = f"lap {_seconds(delta)} s" if delta is not None and lap_worse else ""
        revert = build_recommendation(
            back,
            finding_id=targets[0] if targets else "last-change",
            reason=" · ".join(p for p in ("Last change hurt", lap_token, *parts[:1]) if p),
            detail=f"The last change ({descs[0]}) {effect}. Undo it before trying something else.",
            confidence=0.6,
            unit_system=unit_system,
            tune_values=tune_values,
            step=abs(c.to_value - c.from_value),
            suggested=c.from_value,
            rec_id=f"revert-{slug}",
        )
    return verdict, revert


# --- Choosing the next change ---------------------------------------------------------------
def _choose(
    findings: Sequence[Finding],
    drivetrain: str,
    unit_system: str,
    tune_values: dict[str, float],
    verdict: Verdict | None,
    revert: Recommendation | None,
) -> tuple[Recommendation | None, list[Recommendation]]:
    helped: tuple[str, int] | None = None
    if verdict is not None and verdict.result == "helped" and len(verdict.changes) == 1:
        helped = (verdict.changes[0].setting, _change_dir(verdict.changes[0]))

    cands: list[Candidate] = []
    for f in findings:
        for ch, prior in applicable_changes(f.id, drivetrain, f.axle, tune_values, unit_system):
            score = f.severity * f.confidence * f.consistency * prior
            if helped and ch.setting == helped[0] and ch.direction == -helped[1]:
                score *= 0.3  # don't undo a change that just helped
            cands.append((score, f, ch, prior))
    cands.sort(key=lambda c: -c[0])

    def make(c: Candidate, priority: int) -> Recommendation:
        _, f, ch, prior = c
        return build_recommendation(
            ch,
            finding_id=f.id,
            reason=f.evidence,
            detail=reason_text(f.detail or f.evidence, ch.why),
            confidence=f.confidence * prior,
            unit_system=unit_system,
            tune_values=tune_values,
            priority=priority,
        )

    best = next(
        (
            c
            for c in cands
            if not c[2].setting.startswith("tires.")
            and c[1].confidence * c[3] >= MIN_NEXT_CHANGE_CONFIDENCE
            and c[0] >= MIN_NEXT_CHANGE_SCORE
        ),
        None,
    )
    if revert is None and best is None:
        return None, []

    if revert is not None:
        first, used = revert, {revert.setting}
    else:
        assert best is not None
        first, used = make(best, 1), {best[2].setting}

    # Alternatives in order of preference: the regular best change (when the first
    # one is a revert), another fix for the same problem, the best fix for the next
    # problem, then whatever scores highest.
    top = best[1] if best is not None else None
    prefs: list[Callable[[Candidate], bool]] = [
        lambda c: revert is not None and c is best,
        lambda c: c[1] is top,
        lambda c: c[1] is not top,
        lambda c: True,
        lambda c: True,
    ]
    picked: list[Candidate] = []
    for pref in prefs:
        if len(picked) == 2:
            break
        c = next(
            (
                c
                for c in cands
                if c[0] >= MIN_ALTERNATIVE_SCORE and c[2].setting not in used and pref(c)
            ),
            None,
        )
        if c is not None:
            picked.append(c)
            used.add(c[2].setting)
    alternatives = [make(c, i + 2) for i, c in enumerate(picked[:2])]
    return first, alternatives


# --- Entry point -------------------------------------------------------------------------------
def analyze_session(laps: Sequence[LapAnalysis], ctx: SessionContext) -> SessionAnalysis:
    """Aggregate lap analyses into findings, one next change and a verdict."""
    drivetrain = drivetrain_name(
        ctx.drivetrain if ctx.drivetrain is not None else (laps[0].drivetrain if laps else None)
    )
    tune_values = dict(ctx.tune_values or {})
    valid = [lap for lap in laps if lap.lap_kind == "flying" and lap.valid]
    consistency = _consistency(laps, valid)
    findings = _aggregate(valid, consistency)

    verdict = revert = None
    if ctx.previous_session is not None:
        verdict, revert = _verdict(
            consistency,
            findings,
            ctx.previous_session,
            tuple(ctx.tune_changes),
            ctx.unit_system,
            tune_values,
        )
    next_change, alternatives = _choose(
        findings, drivetrain, ctx.unit_system, tune_values, verdict, revert
    )
    limits = session_limits(tune_values, len(valid), findings, [next_change, *alternatives])
    return SessionAnalysis(
        laps_analyzed=len(valid),
        consistency=consistency,
        findings=tuple(findings),
        next_change=next_change,
        alternatives=tuple(alternatives),
        verdict_on_last_change=verdict,
        limits=tuple(limits),
    )
