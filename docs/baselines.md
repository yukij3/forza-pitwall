# Baseline setups

When a car goes on track, Pitwall shows approximate **starting values** for its
type of car: GT3, LMP2, front-wheel-drive road car and so on. The live tuning
board then fine-tunes from there. The values come from published Forza
Motorsport (2023) tuning guides, posted community tunes and general setup
logic. They are starting points, not optimal tunes for any one car or track.
Every category cites its sources and has a confidence of *low* or *medium*,
never *high*.

```python
from pitwall.baselines import baseline, car_info, categories, match

m = match(car_ordinal=2240, car_pi=949, car_class=7, drivetrain=1)
# Match(category_id="lmp2", how="division", confidence="high",
#       car=CarInfo(2240, "2014 Mazda #70 SpeedSource Lola B12/80", "Forza P2"))
b = baseline(m.category_id, unit_system="metric", drivetrain=1)
b.to_dict()  # {"category": ..., "drivetrain": "RWD", "settings": [...], "sources": [...]}
```

- `categories()` lists all categories in display order.
- `match(car_ordinal, car_pi, car_class, drivetrain)` returns a `Match`, or
  `None` when there is nothing to go on. `drivetrain` is the Data Out integer
  (0 FWD, 1 RWD, 2 AWD) or the name.
- `baseline(category_id, unit_system="imperial", drivetrain=None)` returns a
  `Baseline`. `drivetrain` selects the differential settings. Pass the car's
  drivetrain; by default you get the category's usual one. It raises
  `KeyError` for an unknown category and `ValueError` for an unknown unit
  system.
- `car_info(car_ordinal)` returns a `CarInfo` (ordinal, name, division), or
  `None` for an unknown ordinal.

The module uses only the standard library. Its data is bundled JSON in
`pitwall/baselines/data/`, read once and cached. Every result type has
`to_dict()`.

## Output

A `Baseline` holds one entry per tuning-menu setting that exists for the
drivetrain, in menu order, using the keys, sections and labels of
`pitwall/tune/settings.py`. Differential settings that the drivetrain lacks
are never included.

| Field | Meaning |
|---|---|
| `value`, `range` | Absolute starting value and a sensible range. Only for settings whose in-game scale is the same for every car: tire pressure, camber, toe, caster, anti-roll bars (1–65), damping (1–20), brake balance and pressure, differential. |
| `relative` | A slider position, for example `≈100% of slider (60–100%)`, for aero. |
| `note` | The reasoning, or a rule for settings whose scale differs per car: springs, ride height, final drive and geometry. |
| `basis` | `published` means the value comes from an FM2023 source. `carried_over` means it comes from an FM7 or Forza Horizon source (none are used at the moment). `principles` means a judgment call, made where sources disagree or give no number. |
| `unit` | Taken from the tune's unit system: psi or bar for tire pressure. Data is stored in imperial and converted on the way out. |

`Baseline` also carries `notes`, `sources` (title, url, what each was used
for), `confidence` and `drivetrain` (the drivetrain the differential values
are for).

## Categories

Forza Motorsport (2023) has 51 car divisions. Pitwall groups them into 16
setup archetypes. A division with mixed drivetrains maps to the category for
the car's drivetrain. For example, Modern Hot Hatch is `road_fwd`, `road_awd`
or `road_rwd`.

| Category | Divisions | Drivetrains | Confidence |
|---|---|---|---|
| `road_fwd` Road cars, front-wheel drive | Hot Hatch Icons, Modern Hot Hatch, Early Sport Compact, Modern Sport Compact, Vintage Sport Compact, Sport Touring Classics, Modern Sport Touring | FWD | medium |
| `road_rwd` Road cars, rear-wheel drive | Sport Coupe Icons, Vintage Sport Compact, Early Sport Compact, Modern Sport Compact, Hot Hatch Icons, Modern Hot Hatch, Sport Touring Classics, Vintage Exotic GT | RWD | medium |
| `road_awd` Road cars, all-wheel drive | Early Sport Compact, Modern Sport Compact, Modern Hot Hatch, Hot Hatch Icons, Sport Luxury, Sport Touring Classics, Modern Sport Touring, Sport GT Icons, Modern Sport GT, Modern Sport Coupe | AWD | medium |
| `sports_muscle` Sports, GT and muscle cars | Modern Sport Coupe, Modern Sport GT, Modern Sport Touring, Sport GT Icons, Sport Luxury, Vintage Muscle, Street Drag Racers, Formula Drift | RWD | medium |
| `supercar` Supercars and hypercars (road) | Modern Exotic GT, Modern Hypercars, Exotic GT Classics | RWD, AWD | medium |
| `track_toy` Track toys | Track Toys | RWD | low |
| `track_special` Factory track cars and time-attack specials | Modern Factory Racecars, Early Factory Racecars, Forza Specials, Mission R Spec | RWD, AWD | low |
| `touring` Touring cars | Forza Touring Cars, G40 Junior Spec | FWD, RWD | low |
| `gt4` GT4 race cars | Forza GT4 | RWD, FWD | medium |
| `gt3_gte` GT3 and GTE race cars | Forza GT3, Forza GT2, Super Trofeo, 488 Challenge Spec | RWD | medium |
| `stock_car` Stock cars and V8 sedans | NASCAR, Forza AUS, Forza T/A | RWD | low |
| `vintage_racer` Vintage race cars | Vintage Le Mans Sportscars, Vintage Le Mans Prototypes, Prototype Group Racing, GTX Sportscars, Vintage Trans Am | RWD, AWD | low |
| `lmp2` LMP2, LMP3 and early LMP prototypes | Forza P2, Forza P3, Early LMP | RWD | medium |
| `lmp1_hypercar` LMP1, LMDh and hypercar prototypes | Forza P1, Forza Proto-H | RWD, AWD, FWD | medium |
| `gtp_groupc` Group C and IMSA GTP prototypes | GTP/C | RWD | low |
| `open_wheel` Open-wheel cars | Formula 60s, Formula 70s, Grand Prix Rivals, IndyCar, Formula Mazda Spec, The Birth of Grand Prix | RWD | low |

Three cars are pinned to a category other than their division's: the Mazda
MX-5 Cup is `touring`, the Mazda Furai (built on an LMP2 chassis) is `lmp2`,
and the 1948 Ferrari 166 Inter Sport is `vintage_racer`.

## Starting values

All values below are for each category's usual drivetrain. Tire pressure is in
psi; anti-roll bars use the 1–65 slider and damping the 1–20 slider; brake
balance is % to the front. A `*` marks a value set by judgment
(`basis: principles`). The ranges, the values for other drivetrains and the
reasoning behind every value are in `pitwall/baselines/data/categories.json`.

| Category | Tire psi | Camber F / R | Caster | ARB F / R | Rebound F / R | Bump F / R | Brake bal. / press. | Differential (accel / decel) |
|---|---|---|---|---|---|---|---|---|
| `road_fwd` (FWD) | 28.5 | −1.3 / −1.6 | 6 | 16 / 22 | 9 / 9 | 3.5 / 3.5 | 50 / 100 | F 46 / 0 |
| `road_rwd` (RWD) | 28.5 | −1.6 / −1.3 | 6 | 21 / 17 | 9 / 9 | 3.5 / 3.5 | 50 / 100 | 66 / 25 |
| `road_awd` (AWD) | 30* | −1.4 / −1.4 | 6 | 24 / 22 | 9 / 9 | 3.5 / 3.5 | 50 / 100 | F 66 / 0, R 100 / 25, centre 68 |
| `sports_muscle` (RWD) | 30* | −1.6 / −1.3 | 6 | 24 / 21 | 9.5 / 9.5 | 3.5 / 3.5 | 50 / 100 | 66 / 25 |
| `supercar` (RWD) | 29 | −1.6 / −1.3 | 6 | 14 / 18 | 10 / 10 | 3.5 / 3.5 | 45 / 100 | 70 / 22 |
| `track_toy` (RWD) | 25 | −1.6 / −1.3 | 6 | 6 / 11 | 10 / 10 | 3 / 3 | 45 / 100 | 70 / 22 |
| `track_special` (RWD) | 29 | −1.8 / −1.4 | 6 | 12 / 16 | 10 / 10 | 3.5 / 3.5 | 45 / 100 | 70 / 22 |
| `touring` (FWD) | 29 | −1.8 / −1.4 | 6 | 12 / 17 | 10 / 10 | 3.5 / 3.5 | 45 / 100 | F 50 / 0 |
| `gt4` (RWD) | 29 | −1.8 / −1.4 | 6 | 13 / 12 | 10 / 10 | 3.5 / 3.5 | 45 / 100 | 70 / 22 |
| `gt3_gte` (RWD) | 29 | −1.8 / −1.4 | 6 | 14 / 16 | 10 / 10 | 3.5 / 3.5 | 45 / 100 | 70 / 22 |
| `stock_car` (RWD) | 29.5* | −1.8 / −1.4 | 6 | 17 / 16 | 10 / 10 | 3.5 / 3.5 | 45 / 100 | 66 / 25* |
| `vintage_racer` (RWD) | 25.5 | −1 / −1 | 6.5 | 15 / 14 | 9 / 9 | 3.5 / 3.5 | 45 / 100 | 62 / 30* |
| `lmp2` (RWD) | 28.5 | −1.7 / −1.4 | 6 | 34 / 36 | 10 / 11 | 3 / 4 | 45 / 100 | 85 / 5* |
| `lmp1_hypercar` (RWD) | 28.5 | −1.7 / −1.5 | 6 | 36 / 38 | 10 / 11 | 3 / 4 | 45 / 100 | 85 / 5* |
| `gtp_groupc` (RWD) | 26 | −2 / −1.6 | 6 | 32 / 34 | 10 / 11 | 3 / 4 | 45 / 100 | 80 / 8* |
| `open_wheel` (RWD) | 24 | −1.5 / −2 | 7 | 25 / 27 | 11 / 10 | 4 / 3 | 45 / 100 | 50 / 0 |

Toe starts at 0 for every category. For road cars the rear toe range runs to
−0.3, which is toe-in: in FM2023 the slider's "In" side is the negative side.
Players report the labels and descriptions as confusing (a known issue on the
Forza forums), so check the direction on the car itself.

### Settings whose scale differs per car

- **Springs**: QuickTune's rule, which uses the weight and weight distribution
  shown in the tuning menu. Front ≈ weight ÷ 2 × front weight share × a
  factor, rear ≈ weight ÷ 2 × rear share × a factor (lb/in). The factors
  depend on the car type: street 0.96 / 0.68, sports 0.92 / 0.69, high
  performance 0.89 / 0.73, race 0.88 / 0.72, prototype 0.87 / 0.69,
  GP 0.92 / 0.50. Swap front and rear for front-wheel drive, and double the
  result for 800 hp and up.
- **Ride height**: as low as the slider allows, but not below QuickTune's
  minimum for the car type: road 4–6 in, high performance 3–4 in, race 3–5 in,
  prototype 2.5–3.5 in, GP 2.5–4.5 in. Keep front and rear level. Raise it if
  the car bottoms out; the live board flags bottoming.
- **Aero**: near maximum front and rear, `≈100% of slider (60–100%)`, then trim
  both ends together for tracks with long straights. Front- and all-wheel-drive
  road cars that offer drivetrain swaps start at front max and rear min. This
  applies only to cars with adjustable aero.
- **Final drive**: start from the ratio the build gives you. With Forza's
  standard race gearbox, final drive ≈ 4.25 + 0.01 × (400 − hp) ÷ 6; with any
  other race gearbox, lower it by 0.01 for every 6 hp added over stock. Then
  check the longest straight: if the car hits the limiter before the braking
  point, lower the ratio; if top gear never gets near the limiter, raise it.
- **Geometry** (roll centre, anti-dive, anti-squat): keep the defaults. Both
  ForzaTune and QuickTune start FM2023 tunes there.

## How the values were derived

1. **QuickTune's FM2023 guide is the default.** It is the only published
   FM2023 guide with numbers per car type (street, sports, high performance,
   race, prototype, GP). Each category uses its car type's row. Weight-based
   rules, such as the anti-roll bar formula
   `(weight ÷ 2) ÷ (200 − 200 × stiffness)` split by weight distribution, are
   evaluated at the category's typical stock weight, which the note states.
2. **The majority wins over QuickTune.** Where at least two other FM2023
   sources agree on something different, the value follows them, and
   QuickTune's number stays inside the range. The other sources are the
   ForzaTune guide, a community tuning note, posted tunes on the Forza forums
   and forum threads on tire pressure. The cases where this happened:
   - Brake pressure: 100% rather than QuickTune's 125–145%.
   - Damping: bump around 3.5 and rebound 9–10, which matches posted tunes.
     QuickTune's FM2023 rebound table isn't published as text.
   - Caster on race cars: 6.0 rather than 4–5.
   - Tire pressure on light cars.
3. **Judgment calls are labelled `principles`.** This covers cases where the
   sources disagree and no majority exists, or where they give no number. The
   affected values are tire pressure for heavy road cars and stock cars, and
   the differential for prototypes, Group C, vintage and stock cars. The note
   on each value names the sources it sits between.
4. **Real-world documents are cross-checks only.** Pirelli bulletins for GT3,
   GT4 and TCR, the FIA WEC tyre pressure and camber decision for Hypercar,
   LMP2 and LMGT3, Pirelli's F1 prescriptions and Goodyear's NASCAR numbers
   were used to sanity-check pressures and camber. No value is copied from
   them, because Forza's tire model isn't real life.

On tire pressure: forum players report that FM2023's tuning menu sets the
running pressure, and that pressure barely rises on track, unlike older Forza
games. This hasn't been confirmed officially, but Pitwall treats the values
as running pressures. Sources disagree most on heavy cars. QuickTune adds
5 psi for every 500 lb over 2,999 lb, while posted tunes for heavy cars still
run 27–29 psi.

## Sources

FM2023-specific:

- QuickTune (Fifty Inch), *Forza Motorsport (2023) Tuning Guide, Part 2*:
  <https://forzaquicktune.com/tuning-guide/fm/part2>
- ForzaTune, *The Fully Updated Forza Tuning Guide*:
  <https://forzatune.com/guide/the-fully-updated-forza-tuning-guide/>
- ForzaTune, *Tuning Calculator Support for Forza Motorsport (2023)*:
  <https://forzatune.com/tuning-calculator-support-for-forza-motorsport-2023/>
- ForzaTune, *Forza Motorsport 2023: Tuning Formula Updates in v6.1.0*:
  <https://forzatune.com/forza-motorsport-2023-tuning-formula-updates-in-v6-1-0/>
- SharpSeeEr, *Forza Motorsport tuning notes* (gist, Nov 2023):
  <https://gist.github.com/SharpSeeEr/43cef65cf1cc6e97173ed6fb6640dc8c>
- Official Forza forums (now closed; archived copies):
  - *UI - Tuning - Toe In / Out Labels Reversed* (FM known issues): <https://web.archive.org/web/20260508183458/https://forums.forza.net/t/ui-tuning-toe-in-out-labels-reversed-in-the-tuning-page-1939814/642612>
  - *If you use a wheel, share your tunes with us!*: <https://web.archive.org/web/20260508095622/https://forums.forza.net/t/if-you-use-a-wheel-share-your-tunes-with-us/755425>
  - *What's the deal with tire pressures?*: <https://web.archive.org/web/20260508185340/https://forums.forza.net/t/whats-the-deal-with-tire-pressures-im-barely-seeing-any-pressure-rise-at-all-10-laps/635673>
  - *Tuning question about tire pressures*: <https://web.archive.org/web/20260508095113/https://forums.forza.net/t/tuning-question-about-tire-pressures/714329>

Real-world cross-checks:

- Pirelli, GT World Challenge Asia 2023 tyre bulletin (GT3/GT4):
  <https://www.gt-world-challenge-asia.com/documents/notice/133/GTWCAsia23_01+TechBulletin.pdf>
- Pirelli, Intercontinental GT Challenge California 8h 2018 tyre bulletin (TCR):
  <https://intercontinentalgtchallenge.com/documents/notice/2769/IGTC03TCR_221018+Log+10.pdf>
- FIA WEC, 24 Hours of Le Mans 2026, tyre pressure and camber:
  <https://api.fia.com/sites/default/files/wec_2026_d15_all_tyre_pressure_and_camber_lemans_amended_10062026.pdf>
- Pirelli, 2024 British Grand Prix preview (FIA event notes):
  <https://www.fia.com/sites/default/files/decision-document/2024%20British%20Grand%20Prix%20-%20Event%20Notes%20-%20Pirelli%20Preview.pdf>
- Goodyear, NASCAR Cup at Watkins Glen 2022 (Speedway Digest):
  <https://speedwaydigest.com/index.php/news/nascar-cup-series-news/72117-goodyear-fast-facts-watkins-glen/>

Each category in `categories.json` lists the sources it uses and what it uses
each for.

## Car identification

Data Out sends only `CarOrdinal`, the performance index, a class index and the
drivetrain. `match()` tries these in order:

1. **Ordinal** (`how: "ordinal"`, confidence high): the car is pinned to a
   category in `cars.json`.
2. **Division** (`how: "division"`): the car's in-game division from
   `cars.json`, together with its drivetrain, picks the category. Confidence is
   high, or medium in two cases: the drivetrain has been swapped to one the
   division doesn't normally have, or the drivetrain is unknown and the
   division spans several categories. With a swap, the baseline's
   differential values still match the drivetrain passed in.
3. **Class and drivetrain** (`how: "class_drivetrain"`, confidence low): a
   guess from the class letter and drivetrain. The class letter is derived
   from PI: E ≤ 300, D ≤ 400, C ≤ 500, B ≤ 600, A ≤ 700, S ≤ 800, R ≤ 900,
   P ≤ 998, X = 999. When PI is missing it comes from the packet's class
   index, 0 = E … 8 = X. An unknown drivetrain counts as RWD.

| Class | FWD | RWD | AWD |
|---|---|---|---|
| E, D, C | `road_fwd` | `road_rwd` | `road_awd` |
| B | `road_fwd` | `sports_muscle` | `road_awd` |
| A | `touring` | `sports_muscle` | `road_awd` |
| S | `touring` | `supercar` | `supercar` |
| R | `touring` | `gt3_gte` | `supercar` |
| P | `lmp1_hypercar` | `lmp2` | `lmp1_hypercar` |
| X | `lmp1_hypercar` | `lmp1_hypercar` | `lmp1_hypercar` |

PI can't tell a race car from a road car of the same class, and upgrades move
PI. On stock cars the fallback picks the same category as the division for
56% of the list. It is good for road cars, GT3 and LMP2, and poor for vintage,
open-wheel, stock and track cars. Every car in the bundled list resolves by
ordinal or division, so the fallback only matters for cars added to the game
later.

### The car list (`data/cars.json`)

The list has 681 Forza Motorsport (2023) cars, each with ordinal, name and
division.

- **Ordinals and base names** come from
  [bluemanos/forza-motorsport-car-track-ordinal](https://github.com/bluemanos/forza-motorsport-car-track-ordinal)
  (`fm8/cars.csv`), MIT License, Copyright (c) 2024 Szymon Bluma. The licence
  text is in `pitwall/baselines/data/cars.LICENSE.txt`. That list credits the
  ordinal list Turn 10 posted in the official forums' Data Out thread. It also
  contains Forza Horizon 5-only cars; Pitwall keeps only cars that are in
  Forza Motorsport (2023).
- **Corrections**: two blank model names were filled in (959, 510). For 36
  cars, a malformed name (such as "Indy '25") was cleaned up, or the year or
  name was corrected where at least two of these agreed against the original:
  Turn 10's posted list, the Kudosprime car database and a community data
  export. One car missing from the list (2014 Cadillac CTS-V Sport Wagon) was
  added.
- **Divisions** are the current in-game divisions, cross-checked between the
  same three sources. Turn 10's list predates the 2024 split of "Forza GT"
  into GT2, GT3 and GT4. The sources disagreed on four cars; those were
  resolved by majority, or by the Kudosprime listing when there was no
  majority.

## Limits

- These are starting points for a category, not tunes for a car. Two cars in
  the same category can differ a lot in weight, power and tires. The rules in
  the notes, such as weight-based springs and pressure, close part of that gap.
- One systematic FM2023 source (QuickTune) underpins most values. Other
  sources mostly confirm direction and rough size. Where they disagree, the
  ranges are wide.
- Pressures assume the car's usual compound: road cars on Sport tires, race
  cars on slicks. Stock-weight cars without weight-reduction upgrades want
  different bars, springs and pressures (see QuickTune).
- Game slider limits used for validation (pressure 15–55 psi, camber and toe
  ±5°, caster 1–7°, bars 1–65, damping 1–20, brake pressure 0–200%) are
  assumptions, not taken from official documentation.
- Data Out can't read the current tune, tire pressures or camber. Pitwall
  can't check whether a baseline was applied; the live board judges the
  result by how the car behaves.
