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
# Every window is in seconds, never in frames: the PC game sends 120-160 packets/s.
SMOOTH_WINDOW_S = 0.12  # centred moving average for lateral/long. g, yaw rate, steer
DEFAULT_DT_S = 1 / 60  # only until the first real time step is known
MAX_FRAME_GAP_S = 0.25  # larger gaps between packets count as one ordinary step
# Discontinuities. A rewind steps the race clock back 3-7 s (after a 4-8 s
# pause with no packets); a restart resets it. Segments never span either.
REWIND_MIN_S = 0.5  # race clock stepping back more than this = rewind or restart
JUMP_GAP_S = 1.0  # race clock jumping forward more than this = data dropout
SAMPLE_BUFFER_S = 25.0  # history kept by the streaming segmenter

# --- Wheels ----------------------------------------------------------------------
WHEEL_LOADED_TRAVEL = 0.05  # suspension travel below this = wheel at full droop, no load
RADIUS_MIN_SPEED = 15.0  # m/s; rolling radius is learned from free-rolling wheels ...
RADIUS_MAX_SLIP_RATIO = 0.05  # ... with almost no longitudinal slip ...
RADIUS_MAX_SLIP_ANGLE = 0.5  # ... and little lateral slip, no brake
RADIUS_MIN_SAMPLES = 30
RADIUS_KEEP = 301  # median over the most recent estimates per wheel

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
# Steering held at (nearly) full lock: with a gamepad the front slip angle then
# follows the stick as much as the set-up, so understeer readings built mostly
# from such samples get less confidence and say why.
STEER_PINNED = 0.95
PINNED_SHARE_CAVEAT = 0.5
PINNED_CONFIDENCE_FACTOR = 0.6
YAW_FIT_MIN_LAT_G = 0.20
YAW_FIT_MAX_SLIP = 0.85  # only fit the steering model while both axles grip
YAW_FIT_MIN_STEER = 0.02
YAW_FIT_MIN_CURVATURE = 0.002  # 1/m (radius < 500 m)
YAW_FIT_MIN_S = 1.0  # seconds of in-grip cornering before the yaw model is used
# The yaw model assumes the steering input is proportional to the wheel angle.
# With a gamepad the game sets the wheel angle itself (the stick sits at full
# lock in most corners), so steer/curvature grows with the input instead of
# staying constant. If, at the fit's mean speed, steer/curvature at 75 % input
# is more than this multiple of the value at 25 % input, the model is not used.
YAW_FIT_MAX_NONLINEARITY = 1.5

# --- Wheelspin, lockups, braking stability -----------------------------------
WHEELSPIN_SLIP_RATIO = 1.0
WHEELSPIN_MIN_S = 0.10
# Lockups. With ABS the normalised slip ratio sits around -0.5 and dips past -1
# for a few hundredths of a second all the time (normalised 1.0 is only ~13 %
# real slip), so "slip ratio < -1" is not a lock. A lock is a loaded wheel that
# (nearly) stops: wheel speed at or below LOCK_WHEEL_SPEED_RATIO of road speed,
# or, before the wheel radius is known, a slip ratio this deep.
LOCK_WHEEL_SPEED_RATIO = 0.35
LOCK_DEEP_SLIP_RATIO = -3.0
LOCK_MIN_SPEED = 10.0  # m/s
LOCK_MAX_REAR_SLIP_ANGLE = 1.5  # a lock must start before the car is already sideways
LOCK_GAP_S = 0.03  # flagged samples closer than this belong to one lock
LOCKUP_MIN_S = 0.10  # a lock has to last this long
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
# Peak power is learned from full-throttle samples (Data Out sends power), so
# "gearing too long" means top gear ends the longest straight below the
# peak-power rpm, not below a fixed share of max rpm.
POWER_MIN_THROTTLE = 0.95
POWER_MIN_RPM_PCT = 0.30
POWER_MIN_SPEED = 10.0  # m/s; excludes revving on the grid
POWER_BIN = 0.02  # rpm (fraction of max) bin width
POWER_BIN_KEEP = 200  # recent samples per bin (median)
POWER_MIN_BIN_S = 0.3  # seconds of data before a bin counts
POWER_MIN_BINS = 5
# A higher-rpm bin this far below the best bin proves it is the peak (bin
# medians near the peak are stable to ~0.2 %; automatic gearboxes often shift
# just past the peak, so the visible drop is small).
POWER_PAST_PEAK_DROP = 0.005
# end-of-straight rpm divided by the peak-power rpm: OK at >= 0.97 (power is
# within ~2 % of peak there), bad at <= 0.85
GEARING_PEAK_OK = 0.97
GEARING_PEAK_BAD = 0.85

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
