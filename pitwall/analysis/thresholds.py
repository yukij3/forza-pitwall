"""Every threshold the analysis engine uses, in one place.

Units: seconds, metres, m/s, g (9.80665 m/s^2), °C. Slip angle, slip ratio and
suspension travel are Forza's normalised values: |slip| > 1.0 means the tire is
past its grip peak; suspension travel is 0.0 at full droop and 1.0 at full
compression. ``docs/analysis.md`` explains each value.
"""

from __future__ import annotations

from dataclasses import dataclass

G = 9.80665

# --- Signal conditioning -----------------------------------------------------
SMOOTH_SAMPLES = 7  # centred moving average for lateral/long. g, yaw rate, steer
DEFAULT_DT_S = 1 / 60
MAX_FRAME_GAP_S = 0.25  # larger gaps between packets are treated as one frame
SAMPLE_BUFFER_S = 25.0  # history kept by the streaming segmenter

# --- Pedals -------------------------------------------------------------------
FULL_THROTTLE = 0.95
THROTTLE_ON = 0.50  # "under throttle"
BRAKE_ON = 0.10
HEAVY_BRAKE = 0.30

# --- Corner detection and phases -----------------------------------------------
CORNER_ENTER_G = 0.40  # |lateral g| that starts a corner
CORNER_EXIT_G = 0.25  # |lateral g| below which the corner has ended
CORNER_MIN_SPEED = 8.0  # m/s
CORNER_MIN_DURATION_S = 0.8
CORNER_MIN_HEADING_DEG = 12.0
CORNER_MERGE_GAP_S = 0.5  # same-direction lateral load resuming within this = same corner
CORNER_EXIT_WINDOW_S = 1.5  # time after the corner kept as "exit" (wheelspin, traction)
BRAKE_LOOKBACK_S = 8.0  # how far back a corner's braking zone may start
MID_SPEED_BAND = 0.03  # mid-corner = speed within 3 % of the corner minimum ...
MID_MIN_HALF_S = 0.25  # ... and at least +/-0.25 s around the slowest point
PHASE_LOADED_FRACTION = 0.40  # balance averages use samples above 40 % of peak lateral g
HIGH_SPEED_CORNER = 120 / 3.6  # m/s; corners with a faster minimum speed are "fast"

# --- Balance (+ understeer, - oversteer) ---------------------------------------
SLIP_LIMIT = 1.0  # normalised slip angle at which an axle is past peak grip
BALANCE_SLIP_WEIGHT = 0.7  # front-minus-rear slip angle
BALANCE_YAW_WEIGHT = 0.3  # yaw deficit versus the yaw expected from speed and steering
BALANCE_FLAG = 0.20  # per-sample balance that counts as an understeer/oversteer moment
PHASE_EVENT_MIN_S = 0.12  # flagged time in a phase needed to count a corner as affected
COUNTERSTEER_MIN = 0.03  # steering against the turn (normalised) = oversteer correction
YAW_FIT_MIN_LAT_G = 0.20
YAW_FIT_MAX_SLIP = 0.85  # only fit the steering model while both axles grip
YAW_FIT_MIN_STEER = 0.02
YAW_FIT_MIN_CURVATURE = 0.002  # 1/m (radius < 500 m)
YAW_FIT_MIN_SAMPLES = 60

# --- Wheelspin, lockups, braking stability -----------------------------------
WHEELSPIN_SLIP_RATIO = 1.0
WHEELSPIN_MIN_S = 0.10
LOCKUP_SLIP_RATIO = -1.0
LOCKUP_MIN_S = 0.08
BRAKE_ZONE_MIN_S = 0.40
BRAKE_RELEASE_GAP_S = 0.15
UNSTABLE_REAR_SLIP = 0.80  # rear slip angle while braking in a straight line
UNSTABLE_REAR_MARGIN = 0.25  # ... and this much more than the front
UNSTABLE_MIN_S = 0.10

# --- Bottoming -----------------------------------------------------------------
BOTTOMING_TRAVEL = 0.98
BOTTOMING_MIN_SPEED = 20.0  # m/s; slower hits are kerbs and bumps, not set-up
BOTTOMING_MERGE_S = 0.20

# --- Gearing -------------------------------------------------------------------
LIMITER_RPM_PCT = 0.985
LIMITER_MIN_RUN_S = 0.20  # shorter touches are normal upshifts
STRAIGHT_GAP_S = 0.30  # throttle dips shorter than this don't end a straight
STRAIGHT_MIN_M = 150.0
LONG_STRAIGHT_MIN_M = 250.0  # straights shorter than this don't judge gearing
END_OF_STRAIGHT_S = 0.5  # rpm at the end of a straight = max over its last 0.5 s
GEAR_SETTLED_S = 2.5  # time in the final gear before "rpm at the end" is meaningful
LIMITER_OK_S = 0.3  # limiter time on the longest straight still considered fine
LIMITER_BAD_S = 1.0

# --- Tires ---------------------------------------------------------------------
TIRE_HOT_C = 105.0
TIRE_VERY_HOT_C = 115.0
TIRE_COLD_C = 60.0
TIRE_VERY_COLD_C = 50.0
TIRE_MIN_SECONDS = 30.0


# --- Status bands per board item ----------------------------------------------
@dataclass(frozen=True, slots=True)
class Bands:
    """OK range and the edges where "warn" turns into "bad".

    ``None`` means the side is unbounded (a one-sided metric such as a rate).
    The band score is 0 at an OK edge and 0.5 at the matching bad edge, so
    0 < score <= 0.5 is "warn" and > 0.5 is "bad".
    """

    ok_low: float | None
    ok_high: float | None
    bad_low: float | None
    bad_high: float | None
    min_samples: int


BANDS: dict[str, Bands] = {
    # combined balance (+ understeer, - oversteer), median over corners
    "entry_balance": Bands(-0.05, 0.12, -0.20, 0.30, 3),
    "mid_balance_low": Bands(-0.05, 0.10, -0.20, 0.25, 3),
    "mid_balance_high": Bands(-0.05, 0.10, -0.20, 0.25, 3),
    "exit_balance": Bands(-0.05, 0.10, -0.20, 0.25, 3),
    # share of corner exits with wheelspin on a driven axle
    "exit_wheelspin": Bands(None, 0.10, None, 0.30, 5),
    # share of braking zones with a lockup / with the rear sliding
    "lockups_front": Bands(None, 0.10, None, 0.25, 5),
    "lockups_rear": Bands(None, 0.10, None, 0.25, 5),
    "braking_stability": Bands(None, 0.10, None, 0.25, 5),
    # bump-stop hits at speed in the window; samples = corners seen
    "bottoming_front": Bands(None, 1.0, None, 3.0, 4),
    "bottoming_rear": Bands(None, 1.0, None, 3.0, 4),
    # rpm (fraction of max) at the end of the longest straight in the top gear used
    "gearing": Bands(0.85, None, 0.75, None, 1),
    # front-minus-rear average tire temperature, °C; samples = seconds of data
    "tire_temps": Bands(-8.0, 8.0, -15.0, 15.0, int(TIRE_MIN_SECONDS)),
}

# Rate items need this many events before they can leave "ok", so a single
# mistake never turns an item yellow.
MIN_EVENTS_FOR_WARN = 2
# Board hysteresis in band-score units: a status only changes once the score is
# this far past the edge it crosses.
STATUS_HYSTERESIS = 0.10

# --- Findings, confidence and ranking -----------------------------------------
MIN_FINDING_SEVERITY = 0.10
TIRE_CONFIDENCE = 0.25
GEARING_SHORT_CONFIDENCE = 0.75
GEARING_LONG_CONFIDENCE = 0.45  # Data Out doesn't say how many gears the car has
MIN_NEXT_CHANGE_CONFIDENCE = 0.35
MIN_NEXT_CHANGE_SCORE = 0.05
MIN_ALTERNATIVE_SCORE = 0.02
NO_AERO_PRIOR_FACTOR = 0.5  # tune sheet filled in but without aero values

# --- Session -------------------------------------------------------------------
LAP_TIME_NOISE_MIN_S = 0.15
TARGET_IMPROVED_REL = 0.25
TARGET_IMPROVED_ABS = 0.10
NEW_ISSUE_SEVERITY = 0.30
CONSISTENT_LAP_CV = 0.005
INCONSISTENT_LAP_CV = 0.015
