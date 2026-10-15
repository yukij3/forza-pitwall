"""Peak-power rpm learned from the car's own full-throttle samples.

Data Out sends engine power with every packet, so the power curve doesn't have
to be guessed from ``EngineMaxRpm``: full-throttle samples are binned by rpm
(as a fraction of max rpm) and the bin with the highest median power is the
peak. A peak only counts once a higher-rpm bin shows power falling off;
otherwise the curve may still be rising and the peak is unknown.
"""

from __future__ import annotations

from collections import deque
from statistics import median

from .samples import Sample
from .thresholds import (
    POWER_BIN,
    POWER_BIN_KEEP,
    POWER_MIN_BIN_S,
    POWER_MIN_BINS,
    POWER_MIN_RPM_PCT,
    POWER_MIN_SPEED,
    POWER_MIN_THROTTLE,
    POWER_PAST_PEAK_DROP,
)

_MAX_FORWARD_GEAR = 10


class PowerCurve:
    __slots__ = ("_bins", "_seconds")

    def __init__(self) -> None:
        self._bins: dict[int, deque[float]] = {}
        self._seconds: dict[int, float] = {}

    def add(self, s: Sample) -> None:
        if (
            s.thr < POWER_MIN_THROTTLE
            or s.power <= 0.0
            or s.rpm_pct < POWER_MIN_RPM_PCT
            or s.v < POWER_MIN_SPEED
            or not 1 <= s.gear <= _MAX_FORWARD_GEAR
        ):
            return
        k = int(s.rpm_pct / POWER_BIN)
        d = self._bins.get(k)
        if d is None:
            d = self._bins[k] = deque(maxlen=POWER_BIN_KEEP)
            self._seconds[k] = 0.0
        d.append(s.power)
        self._seconds[k] += s.dt

    def peak_rpm_pct(self) -> float | None:
        """Rpm (fraction of max) of peak power, or None while it isn't proven."""
        meds = {k: median(d) for k, d in self._bins.items() if self._seconds[k] >= POWER_MIN_BIN_S}
        if len(meds) < POWER_MIN_BINS:
            return None
        peak = max(meds, key=lambda k: meds[k])
        top = meds[peak]
        if top <= 0.0:
            return None
        if not any(k > peak and p <= (1.0 - POWER_PAST_PEAK_DROP) * top for k, p in meds.items()):
            return None
        return (peak + 0.5) * POWER_BIN
