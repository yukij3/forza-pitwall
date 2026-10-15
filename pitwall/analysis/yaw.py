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

The model only holds if the steering input is proportional to the wheel angle.
With a gamepad the game picks the wheel angle itself and the stick sits at full
lock through most corners, so the fit also checks that ``steer / curvature``
doesn't grow with the input (a third regressor) and gives no model if it does.
Balance then rests on the slip angles alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from .samples import Sample
from .thresholds import (
    CORNER_MIN_SPEED,
    HEAVY_BRAKE,
    YAW_FIT_MAX_NONLINEARITY,
    YAW_FIT_MAX_SLIP,
    YAW_FIT_MIN_CURVATURE,
    YAW_FIT_MIN_LAT_G,
    YAW_FIT_MIN_S,
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
    """Incremental, time-weighted least-squares fit of :class:`YawModel`."""

    __slots__ = (
        "_corr_steer", "_corr_yaw", "_n", "_sx", "_sy", "_sxx", "_sxy",
        "_sz", "_szz", "_sxz", "_szy",
    )  # fmt: skip

    def __init__(self) -> None:
        self._corr_steer = 0.0
        self._corr_yaw = 0.0
        self._n = 0.0
        self._sx = self._sy = self._sxx = self._sxy = 0.0
        self._sz = self._szz = self._sxz = self._szy = 0.0

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
        w = s.dt  # time-weighted, so the packet rate doesn't matter
        self._n += w
        self._sx += w * x
        self._sy += w * y
        self._sxx += w * x * x
        self._sxy += w * x * y
        self._sz += w * steer
        self._szz += w * steer * steer
        self._sxz += w * x * steer
        self._szy += w * steer * y

    def model(self) -> YawModel | None:
        n = self._n  # seconds of usable samples
        if n < YAW_FIT_MIN_S:
            return None
        mean_y = self._sy / n
        den = n * self._sxx - self._sx * self._sx
        b = 0.0
        if den > 1e-9 * max(1e-9, self._sxx * n):
            b = (n * self._sxy - self._sx * self._sy) / den
        a = (self._sy - b * self._sx) / n
        if any(a + b * v * v <= 0 for v in _V_CHECK):
            a, b = mean_y, 0.0
        if a <= 0 or not self.linear():
            return None
        return YawModel(a, b, self.steer_sign, self.yaw_sign)

    def linear(self) -> bool:
        """False if steer/curvature clearly grows with the steering input (gamepad)."""
        n = self._n
        if n <= 0:
            return True
        # weighted least squares y = a + b*x + c*z (x = v^2, z = steer into the turn)
        m = (
            (n, self._sx, self._sz, self._sy),
            (self._sx, self._sxx, self._sxz, self._sxy),
            (self._sz, self._sxz, self._szz, self._szy),
        )
        sol = _solve3(m)
        if sol is None:
            return True  # too little spread in steer or speed to tell
        a, b, c = sol
        base = a + b * self._sx / n
        low = base + 0.25 * c
        high = base + 0.75 * c
        if low <= 0.0 or high <= 0.0:
            return False
        ratio = high / low
        return 1.0 / YAW_FIT_MAX_NONLINEARITY <= ratio <= YAW_FIT_MAX_NONLINEARITY


def _solve3(m: tuple[tuple[float, ...], ...]) -> tuple[float, float, float] | None:
    """Solve a 3x3 system given as augmented rows (Cramer's rule)."""

    def det(c0: int, c1: int, c2: int) -> float:
        return (
            m[0][c0] * (m[1][c1] * m[2][c2] - m[1][c2] * m[2][c1])
            - m[0][c1] * (m[1][c0] * m[2][c2] - m[1][c2] * m[2][c0])
            + m[0][c2] * (m[1][c0] * m[2][c1] - m[1][c1] * m[2][c0])
        )

    d = det(0, 1, 2)
    scale = abs(m[0][0] * m[1][1] * m[2][2])
    if scale <= 0.0 or abs(d) <= 1e-9 * scale:
        return None
    return det(3, 1, 2) / d, det(0, 3, 2) / d, det(0, 1, 3) / d
