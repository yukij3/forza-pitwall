# Analysis engine

`pitwall.analysis` turns Forza Motorsport (2023) Data Out frames into handling
findings and one tuning change at a time, worded like the game's tuning menu
(`Differential → Acceleration (Rear): −5%`). It is pure Python (standard
library only), does no I/O and keeps no global state.

```python
from pitwall.analysis import (
    LapContext, SessionContext, TuneChange, LiveAnalyzer, analyze_lap, analyze_session,
)

lap = analyze_lap(frames, LapContext(drivetrain=1, lap_kind="flying", lap_valid=True,
                                     tune_values={"arb.front": 20.0}, unit_system="imperial"))
session = analyze_session([lap, ...], SessionContext(
    drivetrain=1, tune_values={...}, unit_system="imperial",
    previous_session=previous_analysis,                       # or None
    tune_changes=[TuneChange("arb.front", 22.0, 20.0)],       # empty if unknown
))
board = LiveAnalyzer(drivetrain=1, tune_values={...}, unit_system="imperial")
snapshot = board.push(frame)        # LiveAnalysis or None; board.snapshot(), board.reset()
```

`drivetrain` is the Data Out integer (0 = FWD, 1 = RWD, 2 = AWD) or the
string. `tune_values` uses the keys of `pitwall/tune/settings.py`, as numbers
shown in the game; it may be empty or partial. `LapContext.lap_time` is an
optional override; otherwise the lap time is the last frame's `current_lap`.

Every result has `to_dict()` with JSON-ready output in the API's canonical
units: m/s, °C, m, s, pedals 0..1. Frames themselves stay in raw game units
(tire temperatures in °F, normalised slip and suspension travel). Lap numbers
in results are 1-based. `pitwall.analysis.__version__` changes whenever results
would change, so callers can invalidate cached analyses.

## Pipeline

Per-lap analysis and the live board share every step:

1. **Samples** (`samples.py`). Each frame becomes a sample: time from the game
   clock (`timestamp_ms`, wrap-safe, gaps over 0.25 s clamped), distance
   integrated from speed, pedals 0..1, steering −1..1, lateral and longitudinal
   g, yaw rate, axle slip angles (mean of |left| and |right|), the extreme slip
   ratio per axle, the most compressed wheel per axle. Lateral g, longitudinal
   g, yaw rate and steering get a 7-sample centred moving average.
2. **Segmentation** (`segments.py`). A streaming segmenter cuts the samples
   into corners, braking zones, full-throttle straights and bottoming hits with
   constant work per sample.
3. **Records** (`records.py`). Each corner, braking zone and straight becomes
   a record (balance per phase, wheelspin on exit, lockups, rpm at the end of a
   straight, and so on).
4. **Assessments** (`assess.py`). Twelve board items, each a value compared
   with its OK band, with evidence and the symptom it points to.
5. **Findings and recommendations** (`rules.py`). Items outside their band
   become findings; the rulebook maps each finding to single-setting changes.

### Corners and phases

A corner starts when |lateral g| reaches **0.40 g** at **8 m/s** or more and
is backdated to where it first exceeded **0.25 g**. It ends when |lateral g|
drops below 0.25 g. Load in the same direction that resumes within **0.5 s**
continues the same corner; a change of direction starts a new one (chicanes are
two corners). Corners shorter than **0.8 s** or turning less than **12°**
(integrated yaw rate) are ignored. The segmenter keeps **1.5 s** after the
corner as its exit window and includes the braking zone leading into it (up to
**8 s** back).

Inside the corner:

- **Mid-corner**: samples within **3 %** of the corner's minimum speed, and at
  least ±0.25 s around the slowest point.
- **Entry**: from turn-in to mid-corner (trail braking and turn-in).
- **Exit**: from mid-corner to the end of lateral load (throttle application).
  Wheelspin is also searched in the exit window after the corner.

A corner whose minimum speed is at least **120 km/h (33.3 m/s)** is *fast*,
otherwise *slow*. Fast-corner balance is where aero changes make sense; slow
corners call for mechanical changes.

### Balance (+ understeer, − oversteer)

Per sample:

- **Slip balance** = front axle slip angle − rear axle slip angle. Data Out's
  slip angles are normalised so 1.0 is the grip peak; the axle closer to (or
  past) its limit is the one giving up.
- **Yaw balance** = 1 − measured path curvature / curvature expected from speed
  and steering, clamped to ±1. The expectation comes from the car's own in-grip
  behaviour: while both axles are below 0.85 slip, a least-squares fit learns
  `steer / curvature = a + b·v²` (wheelbase over steering gain plus the
  understeer gradient and any speed-sensitive steering). The fit also learns
  the sign conventions of steering and yaw rate. Counter-steer (steering
  against the turn while still cornering) counts as −1.
- **Balance** = 0.7 × slip balance + 0.3 × yaw balance (slip balance alone
  until the fit has 60 samples).

A phase's balance is the mean over samples above 40 % of the corner's peak
lateral g. A sample counts as an understeer moment when the front is past 1.0
and balance ≥ +0.20, and as an oversteer moment when the rear is past 1.0 and
balance ≤ −0.20 (or the driver counter-steers with the rear at 0.9 or more).

### Other events

| Event | Rule |
|---|---|
| Wheelspin on exit | throttle ≥ 50 % and a driven-axle slip ratio ≥ 1.0 for ≥ 0.10 s, from mid-corner to the end of the exit window. FWD: front, RWD: rear, AWD: both (the worse axle is reported). |
| Braking zone | brake ≥ 10 % for ≥ 0.4 s (releases shorter than 0.15 s don't end it) |
| Lockup | in a braking zone, a slip ratio ≤ −1.0 on the axle for ≥ 0.08 s |
| Braking instability | brake ≥ 30 %, below corner lateral load, rear slip angle ≥ 0.8 and ≥ 0.25 above the front, for ≥ 0.10 s |
| Bottoming | suspension travel ≥ 0.98 at ≥ 20 m/s, not on a rumble strip; hits closer than 0.2 s are one event |
| Straight | throttle ≥ 95 % (dips under 0.3 s ignored) over ≥ 150 m |
| Limiter | rpm ≥ 98.5 % of max for ≥ 0.2 s at full throttle (shorter touches are upshifts) |

## Lap metrics

`LapMetrics.to_dict()`:

| Field | Meaning |
|---|---|
| `lap_time` | s |
| `distance`, `max_speed`, `avg_speed` | m, m/s |
| `full_throttle_pct`, `braking_pct` | share of lap time at ≥ 95 % throttle / ≥ 10 % brake |
| `corners`, `corners_slow`, `corners_fast` | corners found (corners cut by the lap ends excluded) |
| `balance` | median balance per phase over the lap's corners: `{entry, mid, exit}` |
| `balance_by_speed` | the same for `low` and `high` speed corners |
| `wheelspin_events` | corners with exit wheelspin |
| `lockups` | `{front, rear}` braking zones with a lockup |
| `braking_zones`, `braking_instability_events` | counts |
| `bottoming_events`, `bottoming` | total and `{front, rear}` hits |
| `limiter_time_s` | time on the limiter at full throttle |
| `top_gear_used`, `top_gear_max_rpm_pct` | highest forward gear and its peak rpm (fraction of max) |
| `longest_straight_m`, `end_of_straight_rpm_pct`, `end_of_straight_gear` | longest straight; rpm and gear at its end |
| `tire_temp_avg`, `tire_temp_max` | °C per wheel |
| `tire_wear_delta` | change of the wear value per wheel over the lap (the direction of the game's scale is undocumented, so this is the absolute change) |
| `frames`, `sample_rate_hz` | data volume |

`LapAnalysis.to_dict()` also has `lap_number`, `lap_kind`, `valid`,
`drivetrain`, `lap_time`, `corners` (number, distances, minimum speed, peak
lateral g, speed band, phase balances, wheelspin), `findings`,
`recommendations` (one per finding, best first), `items` (the board for this
lap, without hysteresis) and `limits`.

Finding fields: `id`, `title`, `severity` (0..1), `confidence` (0..1),
`evidence`, `where` (`[{distance, corner}]`, distance in metres from the start
of the lap, corner 1-based or `null` on a straight), `axle`, `item` (the board
item that measures it), `laps` and `consistency` (session only; 1 and 1.0 for
a single lap).

## Board items and status bands

Each item has a value, an OK band and a "bad" edge. The **band score** is 0 at
the OK edge and 0.5 at the bad edge, growing linearly up to 1 (negative inside
the OK band). Status: `ok` (score ≤ 0), `warn` (0 < score ≤ 0.5, yellow), `bad`
(score > 0.5, red), `collecting` (grey) until the item has its minimum samples.
The severity of the matching finding is the score clamped to 0..1; lap and
session findings start at severity 0.10.

| Item | Value | OK | Bad beyond | Min samples | Finding |
|---|---|---|---|---|---|
| `entry_balance` | median entry balance, all corners | −0.05 … +0.12 | −0.20 / +0.30 | 3 corners | `entry-understeer` / `entry-oversteer` |
| `mid_balance_low` | median mid-corner balance, slow corners | −0.05 … +0.10 | −0.20 / +0.25 | 3 | `mid-understeer` / `mid-oversteer` |
| `mid_balance_high` | median mid-corner balance, fast corners | −0.05 … +0.10 | −0.20 / +0.25 | 3 | `high-speed-understeer` / `high-speed-oversteer` |
| `exit_balance` | median exit balance, all corners | −0.05 … +0.10 | −0.20 / +0.25 | 3 | `exit-understeer` / `exit-oversteer` |
| `exit_wheelspin` | share of corner exits with wheelspin | ≤ 0.10 | 0.30 | 5 exits | `exit-wheelspin` |
| `lockups_front` | share of braking zones with a front lockup | ≤ 0.10 | 0.25 | 5 stops | `lockup-front` (`lockup-both` if the rear fails too) |
| `lockups_rear` | same, rear | ≤ 0.10 | 0.25 | 5 stops | `lockup-rear` (or `lockup-both`) |
| `braking_stability` | share of braking zones with rear instability | ≤ 0.10 | 0.25 | 5 stops | `braking-instability` |
| `bottoming_front` | front bottoming hits in the window | ≤ 1 | 3 | 4 corners | `bottoming-front` |
| `bottoming_rear` | rear hits | ≤ 1 | 3 | 4 corners | `bottoming-rear` |
| `gearing` | rpm at the end of the longest straight (≥ 250 m), fraction of max | ≥ 0.85, no limiter | 0.75; limiter: 0.3 s → warn, 1.0 s → bad | 1 straight | `gearing-short` (limiter in the top gear used) / `gearing-long` (top gear used, held ≥ 2.5 s, low rpm) |
| `tire_temps` | front − rear average temperature, °C | ±8 | ±15; also either axle above 105 °C (bad at 115) or below 60 °C (bad at 50) | 30 s | `tires-hot-<axle>` / `tires-cold-<axle>` |

Balance items use the median over corners, so one slide doesn't move them. Rate
items need at least **2 events** before they can leave `ok`.

### Live board

`LiveAnalyzer` keeps the last `window_corners` (default 12) corners and braking
zones, the last 6 straights, bottoming hits since the oldest corner in the
window, and tire temperatures over the window (at least the last 60 s).

- **Cost.** `push()` converts the frame and advances a few state machines (a
  few microseconds). Records are analysed and the board re-rated only when a
  corner, braking zone or straight completes, and only then does `push()`
  return a snapshot.
- **Hysteresis.** A status changes only once the band score is 0.1 past the
  edge it crosses: an `ok` item turns `warn` above 0.1, a `warn` item returns
  to `ok` below −0.1, `bad` needs 0.6 to enter and drops back under 0.4.
- **Focus.** The one `warn`/`bad` item with a recommendation that has the
  highest severity × confidence (`bad` weighted 1.5×). `null` when nothing
  needs fixing.
- **Reset** after a tune change: the window, the steering model and the
  hysteresis memory start over.

`to_dict()`:

```jsonc
{"corners_seen": 23, "window": {"corners": 12, "laps": 1.4},   // laps: null until a full lap has been measured
 "focus": "exit_balance",
 "items": [{"id": "exit_balance", "group": "Balance", "title": "Corner exit",
            "status": "bad", "value": -0.71, "value_text": "Oversteer 0.71",
            "target_text": "−0.05 … +0.10", "samples": 12, "severity": 1.0,
            "confidence": 0.91, "recommendation": { /* Recommendation */ }}]}
```

`value` is numeric in the units of the table above; `value_text` and
`target_text` are ready-made strings (the tire item's text is in °C).

## Recommendations

### Rulebook

Each finding maps to changes in order of preference; the number in brackets is
the rule's prior (how directly the setting addresses the symptom). Candidates
are dropped when the setting doesn't exist for the drivetrain
(`settings.py`), when a rule is limited to some drivetrains or to the axle the
symptom is on, and when the tune sheet shows the setting already at the end of
its range.

| Finding | Changes (imperial steps) |
|---|---|
| `entry-understeer` | Differential → Deceleration (Rear): −5% [RWD/AWD] (1)<br>Differential → Deceleration (Front): −5% [FWD] (1)<br>Brake → Braking Balance: −1% (more rear) (0.8)<br>Anti-roll Bars → Front: −2 (0.7) |
| `mid-understeer` | Anti-roll Bars → Front: −2 (1)<br>Anti-roll Bars → Rear: +2 (0.8)<br>Springs → Front: −50 lb/in (0.7) |
| `high-speed-understeer` | Aero → Downforce (Front): +10 lb (0.9)<br>Aero → Downforce (Rear): −10 lb (0.75)<br>Anti-roll Bars → Front: −2 (0.6) |
| `exit-understeer` | Differential → Acceleration (Front): −5% [FWD] (1)<br>Differential → Center Balance: +5% (more rear) [AWD] (1)<br>Anti-roll Bars → Front: −2 (0.8)<br>Anti-roll Bars → Rear: +2 (0.7) |
| `entry-oversteer` | Differential → Deceleration (Rear): +5% [RWD/AWD] (1)<br>Brake → Braking Balance: +1% (more front) (0.85)<br>Anti-roll Bars → Rear: −2 (0.6) |
| `mid-oversteer` | Anti-roll Bars → Rear: −2 (1)<br>Anti-roll Bars → Front: +2 (0.8)<br>Springs → Rear: −50 lb/in (0.7) |
| `high-speed-oversteer` | Aero → Downforce (Rear): +10 lb (0.9)<br>Aero → Downforce (Front): −10 lb (0.75)<br>Anti-roll Bars → Rear: −2 (0.6) |
| `exit-oversteer` | Differential → Acceleration (Rear): −5% [RWD/AWD] (1)<br>Anti-roll Bars → Rear: −2 (0.8)<br>Differential → Center Balance: −5% (more front) [AWD] (0.7)<br>Springs → Rear: −50 lb/in (0.6) |
| `exit-wheelspin` | Differential → Acceleration (Rear): −5% [rear axle] (1)<br>Differential → Acceleration (Front): −5% [front axle] (1)<br>Differential → Center Balance: −5% (more front) [AWD, rear axle] (0.8)<br>Differential → Center Balance: +5% (more rear) [AWD, front axle] (0.8)<br>Anti-roll Bars → Rear: −2 [rear axle] (0.6)<br>Anti-roll Bars → Front: −2 [front axle] (0.6) |
| `lockup-front` | Brake → Braking Balance: −1% (more rear) (1)<br>Brake → Braking Pressure: −5% (0.8) |
| `lockup-rear` | Brake → Braking Balance: +1% (more front) (1)<br>Brake → Braking Pressure: −5% (0.7) |
| `lockup-both` | Brake → Braking Pressure: −5% (1) |
| `braking-instability` | Brake → Braking Balance: +1% (more front) (1)<br>Differential → Deceleration (Rear): +5% [RWD/AWD] (0.8) |
| `bottoming-front` | Springs → Ride Height (Front): +0.2 in (1)<br>Springs → Front: +50 lb/in (0.8), the choice when ride height is already high<br>Damping → Bump Stiffness (Front): +0.5 (0.6) |
| `bottoming-rear` | Springs → Ride Height (Rear): +0.2 in (1)<br>Springs → Rear: +50 lb/in (0.8)<br>Damping → Bump Stiffness (Rear): +0.5 (0.6) |
| `gearing-short` | Gearing → Final Drive: −0.10 (longer) (1) |
| `gearing-long` | Gearing → Final Drive: +0.10 (shorter) (1) |
| `tires-hot-front` / `-rear` | Tires → Tire Pressure (axle): +0.5 psi (1) |
| `tires-cold-front` / `-rear` | Tires → Tire Pressure (axle): −0.5 psi (1) |

Notes:

- **Final Drive**: in Forza a higher number is a shorter ratio (more
  acceleration, less speed per gear). On the limiter before the braking point →
  lower it; the top gear used ending the longest straight well below the
  limiter → raise it.
- **Aero** rules assume adjustable aero. If the tune sheet has values but none
  for aero, aero changes get half their prior, so the mechanical alternative
  leads.
- **Tire pressure** changes are direction-only and low confidence (0.25);
  they are never the session's next change, only an alternative.

### Steps and wording

| Setting | Imperial | Metric |
|---|---|---|
| Anti-roll bars | 2 | 2 |
| Springs | 50 lb/in | 1.0 kgf/mm |
| Ride height | 0.2 in | 0.5 cm |
| Damping | 0.5 | 0.5 |
| Aero | 10 lb | 5 kgf |
| Braking balance | 1 % | 1 % |
| Braking pressure | 5 % | 5 % |
| Differential (incl. center balance) | 5 % | 5 % |
| Final drive | 0.10 | 0.10 |
| Tire pressure | 0.5 psi | 0.03 bar |

The text is `Section → Label (Axle): ±step unit`, or `Section → Axle` when the
label repeats the section (`Anti-roll Bars → Front: −2`), with a hint for
settings whose direction isn't obvious (`(more front)`, `(longer)`).
`suggested_value` is filled only when `tune_values` has the current value; it
is clamped to known in-game ranges (anti-roll bars 1–65, differential and
balances 0–100 %, otherwise not below zero).

Recommendation fields: `id` (`<setting>-up|down`, or `revert-<setting>`),
`finding_id`, `setting`, `section`, `label`, `axle`, `direction`, `step`,
`step_unit`, `suggested_value`, `text`, `reason` (evidence plus the mechanism),
`confidence`, `priority`.

## Confidence

| Finding type | Confidence |
|---|---|
| Balance | 0.3 + 0.2 × share of corners with the same sign + 0.2 × share whose yaw balance agrees + 0.2 × share of corners with flagged moments + 0.1 × min(1, corners / 8), capped at 0.95 |
| Wheelspin, lockups, instability | 0.5 + 0.3 × min(1, events / 4) + 0.2 × min(1, samples / 8) |
| Bottoming | 0.5 + 0.1 × min(3, hits) + 0.1 if at two or more spots |
| Gearing | 0.75 (limiter), 0.45 (too long; Data Out doesn't give the gear count) |
| Tires | 0.25 |

A recommendation's confidence is the finding's confidence × the rule prior.

## Session analysis

- Only laps with `lap_kind == "flying"` and `valid` count.
- A finding seen in fewer than 30 % of three or more laps is dropped as a
  one-off. Session severity is the median over the laps where it appeared;
  `consistency` is the share of valid laps where it appeared. Confidence is
  the mean lap confidence × a lap-count factor (0.6 for one lap, 0.8 for two)
  × (0.5 + 0.5 × consistency) × a driver factor from lap-time spread (1.0 when
  the coefficient of variation is ≤ 0.5 %, 0.9 up to 1.5 %, 0.75 above).
- **Next change**: every applicable rule of every finding is scored
  severity × confidence × consistency × prior. The best one with confidence
  ≥ 0.35 and score ≥ 0.05 (tire pressure excluded) is `next_change`.
- **Alternatives** (up to 2, different settings): another fix for the same
  finding, then the best fix for the next finding, then the highest scores.
- `consistency`: `laps_total`, `laps_valid`, `lap_numbers`, `lap_times`,
  `best`, `median`, `mean`, `stdev`, `spread`, `cv`, `rating`
  (`consistent` / `variable` / `inconsistent`).

### Verdict on the last change

With a `previous_session`:

- `lap_time_delta` = median valid lap time now − before. Lap-to-lap noise is
  max(0.15 s, mean of the two sessions' standard deviations).
- `finding_deltas` = `{id: {before, after, delta}}` with severity ×
  consistency per finding.
- The target findings of a change are the ones whose rules use that setting in
  that direction, plus the finding the previous session's `next_change`
  addressed if it used the same setting.
- `result`: a *gain* is a median lap faster beyond noise or a target finding
  down by ≥ 25 %; a *loss* is a lap slower beyond noise, a target finding up by
  as much, or a new finding with severity ≥ 0.3. Gain only → `helped`, both →
  `mixed`, loss only → `hurt`, neither → `no-clear-effect`. With an empty
  `tune_changes` the result is `no-change-recorded` (lap times are still
  compared).
- `changes`: `[{setting, from, to}]`; the text names each in menu terms
  (`Anti-roll Bars → Front: 20 → 18`). With several changes at once it says the
  effect can't be attributed to one of them.
- When a single change made things worse, `next_change` is its revert
  (`revert-<setting>`, back to the previous value) and the regular best change
  moves to the alternatives. A setting whose last change helped isn't
  immediately recommended in the opposite direction (its score is cut to 30 %).

## Synthetic laps

`pitwall.analysis.synthetic` generates deterministic Data Out frames for tests,
demos and simulators: a point-mass car (friction circle with aero, power and
drag limits, six-speed gearbox) laps a closed 4.1 km track with eight corners
(five slow, three fast). Issues are injected on top of the ideal lap:

`none`, `understeer`, `high-speed-understeer`, `oversteer-entry`,
`oversteer-exit`, `unstable-braking`, `wheelspin`, `lockup-front`,
`lockup-rear`, `bottoming`, `bottoming-rear`, `gearing-short`, `gearing-long`
(combinations allowed).

```python
from pitwall.analysis.synthetic import SyntheticDriver, generate_lap, generate_laps

frames = generate_lap("wheelspin", drivetrain="FWD", seed=3)
laps = generate_laps("lockup-rear", 3, drivetrain="RWD", seed=1)
for frame in SyntheticDriver("understeer", seed=7).frames():   # endless stream
    ...
```

Same arguments, same frames. Laps from one driver are continuous (time, lap
number, last/best lap, distance, tire temperatures and wear carry over). Frame
`lap_number` is the raw 0-based game value.

## Known limits

- **Tire pressure and camber.** Data Out has no pressures and one temperature
  per tire, so pressure advice is direction-only and camber isn't judged.
  Check Telemetry → Heat in game.
- **The tune.** It isn't in the stream; suggested values exist only for
  settings entered in the tune sheet. Whether the car has adjustable aero is
  unknown.
- **Gear count.** Not in the stream. "Gearing too long" means the highest gear
  used ends the longest straight below 85 % rpm; an unused top gear can't be
  seen directly.
- **Steering assists.** The yaw model learns the steering-to-curvature relation
  per car and session, but controller assists that change with speed blur it.
  Slip angles carry most of the balance weight for that reason.
- **Lap validity.** Track-limit penalties aren't in Data Out; laps the game
  invalidated may still count.
- **Driver vs car.** Findings describe what the car did. A single mistake
  doesn't change a rating (medians, minimum event counts, hysteresis), but a
  consistent driving habit looks the same as a set-up trait.
- **Tire wear.** The direction of the game's wear scale is undocumented, so
  only the per-lap change is reported.
- **Thresholds** come from vehicle-dynamics reasoning and synthetic laps, not
  yet from a large set of real recordings. They all live in
  `pitwall/analysis/thresholds.py`.
