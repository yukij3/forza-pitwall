# Architecture

Pitwall is one Python process (asyncio) that receives Forza Motorsport (2023)
Data Out telemetry, rates the car's handling live, records sessions, analyses
them and serves a web UI. There are no external services: everything it stores
lives in one data directory, as a SQLite database plus raw packet files.

```
Forza Motorsport (Data Out) ──UDP──▶ receiver
                                        │
               ┌────────────────────────┼──────────────────────────┐
               ▼                        ▼                          ▼
           recorder                live board ── snapshots ──▶ live hub
               │                                                   │
               ▼                                                   ▼
storage (SQLite + raw packets)                            WebSocket /ws/live
               │                                                   │
               ▼                                                   │
        analysis runner ──▶ analysis engine                        │
               │                                                   │
               ▼                                                   ▼
          REST /api/* ◀─────────────────────────────────▶ web UI (static, /)
```

## Modules

| Path | Responsibility |
|---|---|
| `pitwall/telemetry/model.py` | `Frame`: one Data Out packet as a frozen dataclass, in the game's raw units. Shared by every other module. |
| `pitwall/telemetry/` | Car Dash packet parsing and encoding, the UDP receiver, splitting a recording into laps. |
| `pitwall/storage/` | SQLite database (sessions, laps, settings, cached analysis results) and raw packet files. |
| `pitwall/analysis/` | Per-lap and per-session analysis, the live tuning board (`LiveAnalyzer`) and the rulebook that maps findings to settings. Pure functions: no I/O, no global state. |
| `pitwall/baselines/` | The car list (ordinal to name and division) and baseline setups per car category. Pure functions over bundled JSON. |
| `pitwall/services/` | The parts that connect the others: the recorder, the live board runner, the analysis runner with its result cache, the baseline adapter and the loader for a lap's frames. |
| `pitwall/api/` | REST API under `/api` and the live WebSocket at `/ws/live` (FastAPI). |
| `pitwall/tune/settings.py` | The canonical list of tune settings: a stable key per setting, with the in-game section, label, axle, units and the drivetrains it exists for, in tuning-menu order. |
| `pitwall/tools/` | Simulator (synthetic telemetry), replay of recorded packet files, and `reindex`, which rebuilds laps and analysis from raw packets. |
| `pitwall/app.py`, `config.py`, `__main__.py` | Wiring, configuration from environment variables, and the `serve` / `simulate` / `replay` / `reindex` commands. |
| `web/` | The browser UI: static HTML, CSS and JavaScript modules, served at `/`. No build step and no CDN, because a home LAN may be offline. |

`pitwall.analysis` and `pitwall.baselines` are loaded lazily. If one of them
can't be imported, the endpoints that need it answer 503 and the rest of the
app keeps working.

## Data flow

### Live

The receiver listens all the time, whether or not anything is being recorded.
Each packet is parsed into a `Frame` and handed to the recorder, the live
board and the live hub. The hub sends a reduced telemetry message over
`/ws/live` at `PITWALL_LIVE_HZ` (20 per second by default) and a status message
(packet rate, recording state, current car) when something changes and at least
once a second. The UI's live view and its "no packets yet" setup hint are
driven by these messages.

### Live tuning board

The board rates the car while you drive, with or without a recording.

- Race-on frames go to a `LiveAnalyzer` on a worker thread through a bounded
  queue. A slow analyzer never blocks the receiver; when the queue is full,
  new frames are dropped and counted.
- The analyzer keeps a rolling window of the last 12 corners and braking zones
  and rates 12 items (balance on entry, mid-corner and exit, wheelspin,
  lockups, braking stability, bottoming, gearing, tire temperatures) as OK,
  Watch, Fix or Collecting. One item is the focus. It uses the same corner
  detection, item bands and rulebook as the per-lap analysis.
- The analyzer is rebuilt when the car or track changes, and when the player
  presses **Reset board** after changing the setup (`POST
  /api/live-analysis/reset`).
- Snapshots go out as `live_analysis` messages on `/ws/live`, at most twice a
  second and only when they changed. `GET /api/live-analysis` returns the
  latest one.

### Recording

A **session** is one recording, from Start to Stop. It is started and stopped
from the UI, or, with the optional auto-record setting, started when the game
reports that a race is on and stopped after 30 seconds without one. A session
remembers the car (numeric ID, class, performance index, drivetrain) and the
track ID.

While recording:

- Every race-on packet is stored as received, with its receive time. Packets
  sent while the game reports no race (menus, pause, the rewind screen) are not
  recorded, except one marker each time the game leaves the race, so the
  recording can be cut into laps again exactly as it was live.
- Frames are split into **laps** at line crossings: the lap number going up,
  or the lap timer restarting after a grid start. A race finish ends the last
  lap when the car is near the line. Each lap is labelled as an out lap,
  flying lap, in lap or partial lap, and is marked invalid, with a reason, when
  it contains a rewind, a pause or a data gap.

The rules are in [storage.md](storage.md#how-laps-are-cut).

### Analysis

The analysis engine is called with frames and context and returns plain
results; it never reads or writes storage itself. The analysis runner in
`pitwall/services/` loads the frames, calls the engine on a worker thread and
caches the result in the database, keyed by a fingerprint of everything the
result depends on (engine version, unit setting, laps), so a stale result is
recomputed automatically.

- `analyze_lap(frames, context)` produces lap metrics (for example lap time,
  throttle and braking share, corner balance on entry, mid-corner and exit,
  wheelspin, lockups, bottoming out, time on the rev limiter, tire temperatures
  and wear) and findings, each with its evidence and where on the lap it
  happened. The full list is in [analysis.md](analysis.md).
- `analyze_session(laps, context)` combines the laps of a session into
  findings, the **one** next change, up to two alternatives, lap-time
  consistency and a list of things the telemetry cannot tell.

The rules it follows:

- Only valid flying laps count towards session findings.
- A recommendation always names one setting, in the game's menu terms: section,
  setting, axle, direction and step (`Anti-roll Bars → Front: −2`). Pitwall
  doesn't know the current tune, so there is no target value.
- Settings that do not exist for the car's drivetrain are never recommended.
- When a conclusion depends on something Data Out does not send (tire pressure,
  temperature across the tread), the result says so.

When a lap is completed, the API pushes `lap_completed`, analyses the lap and
then pushes `analysis_ready` over the WebSocket so the UI can refresh without
polling.

The engine can also take the current tune values, the changes since the
previous session and that session's analysis, and then gives target values
and a verdict on the last change. v1 tracks no tunes, so the server passes
none of these. Tune tracking is on the roadmap.

### Baselines

`pitwall/baselines/` maps the car on track to one of 16 setup categories
(covering all 51 in-game divisions) and returns approximate starting values for
every tuning-menu setting. It matches by car ordinal first (a pinned category
or the car's division), then guesses from class, drivetrain and performance
index. The same car list gives the status message the car's name and division.
The player can pick another category by hand; the differential values still
follow the car's drivetrain. See [baselines.md](baselines.md).

### Reindex

`python -m pitwall reindex` re-reads the raw packet files and rebuilds each
session's laps and cached analysis. Use it after an update that changes how
laps are cut or analysed. See [storage.md](storage.md#rebuilding-laps-reindex).

## Units

Frames keep the game's raw units: tire temperatures in °F, pedals 0 to 255,
steering −127 to 127, and so on. Conversion happens once, at the API boundary.
Everything the API returns uses m/s, °C, metres, seconds, radians, pedals 0..1
and steering −1..1. The UI converts for display according to the user's unit
settings (km/h or mph, °C or °F, psi or bar). The pressure unit also decides
whether recommendation steps and baselines use the game's imperial or metric
units.

## Why raw packets are kept

Pitwall stores every recorded packet as the bytes it received, not just the
parsed and derived data:

- **The analysis will change.** Thresholds get tuned, metrics get added, bugs
  get fixed. With the raw packets, `reindex` can analyse an old session again
  with newer code instead of leaving it with what an older version computed.
- **Parsing can be wrong.** If a field turns out to be interpreted incorrectly,
  the fix can be applied to past recordings too.
- **Replay.** Recorded files can be played back with `python -m pitwall replay`
  to develop and test without the game.
- **It is cheap.** A Car Dash packet is 331 bytes. At 60 to 160 packets per
  second that is 20 to 53 KB/s before compression; the files are
  gzip-compressed and written only while recording and on track.

The file format is described in [storage.md](storage.md).

## Data Out notes

- Packet format "Car Dash" ("Dash" in the official documentation): 331 bytes,
  little-endian. It is the Sled section (232 bytes), the Dash section (79
  bytes), and two Forza Motorsport (2023) additions: tire wear for each wheel
  (4 × f32) and the track ID (s32).
- The game sends 60 packets per second on console and 120 to 160 on PC. Pitwall
  takes time from the race clock, not from the packet count.
- The race-on flag is 0 in menus and while paused.
- Rewinds make the race clock, the current lap time and the distance travelled
  jump backwards.
- Not in the stream: tire pressure, temperature across the tread (one value per
  tire), the current tune, car and track names (numeric IDs only), lap
  validity, driver aids.
- Official field list:
  [Forza Motorsport "Data Out" Documentation](https://support.forza.net/hc/en-us/articles/21742934024211-Forza-Motorsport-Data-Out-Documentation).
  More detail in [data-out.md](data-out.md).

## Deployment

The Docker image runs the same process as an unprivileged user, receives
telemetry on 5300/udp, serves the UI and API on 5301/tcp, keeps its data in the
`/data` volume and reports healthy when `/api/status` answers. Pitwall is meant
for a local network and has no authentication. See [install.md](install.md).

## Further reading

- [install.md](install.md): installation, configuration, troubleshooting
- [api.md](api.md): REST and WebSocket reference
- [storage.md](storage.md): database schema, raw packet file format, lap rules
- [data-out.md](data-out.md): packet layout and field notes
- [analysis.md](analysis.md): metrics, thresholds, rules and limits
- [baselines.md](baselines.md): car categories, starting values and sources
