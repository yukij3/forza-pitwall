"""Expected yaw rate from speed and steering.

While both axles have grip, a car's path curvature follows the steady-state
bicycle model ``steer / curvature = a + b * v^2`` (``a`` ~ wheelbase over the
steering gain, ``b`` ~ the understeer gradient plus any speed-sensitive steering
assist). :class:`YawFit` learns ``a`` and ``b`` from the car's own in-grip
samples with incremental least squares, so it costs a few operations per frame.

Measured against that model, a car that yaws less than its steering asks for is
understeering and one that yaws more (or needs counter-steer) is oversteering.
The fit also learns the sign conventions of steering and yaw rate relative to
lateral acceleration, so nothing depends on the game's axis conventions.
"""

from __future__ import annotations

from dataclasses import dataclass

from .samples import Sample
from .thresholds import (
    CORNER_MIN_SPEED,
    HEAVY_BRAKE,
    YAW_FIT_MAX_SLIP,
    YAW_FIT_MIN_CURVATURE,
    YAW_FIT_MIN_LAT_G,
    YAW_FIT_MIN_SAMPLES,
    YAW_FIT_MIN_STEER,
)

_V_CHECK = (CORNER_MIN_SPEED, 90.0)


@dataclass(frozen=True, slots=True)
class YawModel:
    a: float
    b: float
    steer_sign: int  # +1 if positive steer turns toward positive lateral g
    yaw_sign: int  # +1 if positive yaw rate goes with positive lateral g

    def expected_curvature(self, steer_into_turn: float, v: float) -> float | None:
        den = self.a + self.b * v * v
        if den <= 1e-6:
            return None
        return steer_into_turn / den


class YawFit:
    """Incremental least-squares fit of :class:`YawModel`."""

    __slots__ = ("_corr_steer", "_corr_yaw", "_n", "_sx", "_sy", "_sxx", "_sxy")

    def __init__(self) -> None:
        self._corr_steer = 0.0
        self._corr_yaw = 0.0
        self._n = 0
        self._sx = self._sy = self._sxx = self._sxy = 0.0

    @property
    def steer_sign(self) -> int:
        return 1 if self._corr_steer >= 0 else -1

    @property
    def yaw_sign(self) -> int:
        return 1 if self._corr_yaw >= 0 else -1

    def add(self, s: Sample) -> None:
        lat = s.lat_g
        if s.v < CORNER_MIN_SPEED or -YAW_FIT_MIN_LAT_G < lat < YAW_FIT_MIN_LAT_G:
            return
        self._corr_steer += s.steer * lat
        self._corr_yaw += s.yaw * lat
        if s.brk >= HEAVY_BRAKE or s.sa_f >= YAW_FIT_MAX_SLIP or s.sa_r >= YAW_FIT_MAX_SLIP:
            return
        turn = 1.0 if lat > 0 else -1.0
        steer = s.steer * self.steer_sign * turn
        yaw = s.yaw * self.yaw_sign * turn
        if steer < YAW_FIT_MIN_STEER or yaw <= 0.0:
            return
        curvature = yaw / s.v
        if curvature < YAW_FIT_MIN_CURVATURE:
            return
        x = s.v * s.v
        y = steer / curvature
        self._n += 1
        self._sx += x
        self._sy += y
        self._sxx += x * x
        self._sxy += x * y

    def model(self) -> YawModel | None:
        n = self._n
        if n < YAW_FIT_MIN_SAMPLES:
            return None
        mean_y = self._sy / n
        den = n * self._sxx - self._sx * self._sx
        b = 0.0
        if den > 1e-9 * max(1.0, self._sxx * n):
            b = (n * self._sxy - self._sx * self._sy) / den
        a = (self._sy - b * self._sx) / n
        if any(a + b * v * v <= 0 for v in _V_CHECK):
            a, b = mean_y, 0.0
        if a <= 0:
            return None
        return YawModel(a, b, self.steer_sign, self.yaw_sign)
