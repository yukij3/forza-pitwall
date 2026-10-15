# Architecture

Pitwall is one Python process (asyncio) that receives Forza Motorsport (2023)
Data Out telemetry, records it, analyses it and serves a web UI. There are no
external services: everything it stores lives in one data directory, as a
SQLite database plus raw packet files.

```
Forza Motorsport ──UDP 60 Hz──▶ receiver ──▶ recorder ──▶ storage (SQLite + raw packets)
   (Data Out)                     │              │
                                  ▼              ▼
                           live broadcaster   analysis engine
                                  │              │
                                  ▼              ▼
                        WebSocket /ws/live    REST /api/*  ◀── web UI (static, /)
```

## Modules

| Path | Responsibility |
|---|---|
| `pitwall/telemetry/model.py` | `Frame`: one Data Out packet as a frozen dataclass, in the game's raw units. Shared by every other module. |
| `pitwall/telemetry/` | Car Dash packet parsing and encoding, the UDP receiver, splitting a recording into laps. |
| `pitwall/storage/` | SQLite database (sessions, laps, tunes, settings) and raw packet files. |
| `pitwall/analysis/` | Lap metrics, handling findings, recommendations. Pure functions: no I/O, no global state. |
| `pitwall/api/` | REST API under `/api` and the live WebSocket at `/ws/live` (FastAPI). |
| `pitwall/tune/settings.py` | The canonical list of tune settings: a stable key per setting, with the in-game section, label, axle, units and the drivetrains it exists for, in tuning-menu order. |
| `pitwall/tools/` | Simulator (synthetic telemetry) and replay of recorded packet files, for development without the game. |
| `pitwall/app.py`, `config.py`, `__main__.py` | Wiring, configuration from environment variables, and the `serve` / `simulate` / `replay` commands. |
| `web/` | The browser UI: static HTML, CSS and JavaScript modules, served at `/`. No build step and no CDN, because a home LAN may be offline. |

## Data flow

### Live

The receiver listens all the time, whether or not anything is being recorded.
Each packet is parsed into a `Frame`. The live broadcaster sends a reduced
telemetry message over `/ws/live` at `PITWALL_LIVE_HZ` (20 per second by
default) and a status message (packet rate, recording state, current car) when
something changes and at least once a second. The UI's live view and its "no
packets yet" setup hint are driven by these messages.

### Recording

A **session** is one recording, from Start to Stop. It is started and stopped
from the UI, or, with the optional auto-record setting, started when the game
reports that a race is on and stopped after 30 seconds without one. A session
remembers the car (numeric ID, class, performance index, drivetrain), the track
ID and the tune that was active when it started.

While recording:

- Frames received while the game reports no race (menus, pause) are skipped.
- Every recorded packet is stored as received, with its receive timestamp.
- Frames are split into **laps** when the lap number changes. Each lap is
  labelled as an out lap, flying lap, in lap or partial lap, and is marked
  invalid, with a reason, when a rewind or a pause is detected inside it.
  Rewinds show up as the lap time or the distance travelled jumping backwards.

### Analysis

The analysis engine is called with frames and context and returns plain
results; it never reads or writes storage itself.

- `analyze_lap(frames, context)` produces lap metrics (for example lap time,
  throttle and braking share, corner balance on entry, mid-corner and exit,
  wheelspin, lockups, bottoming out, time on the rev limiter, tire temperatures
  and wear) and findings, each with its evidence and where on the lap it
  happened. The full list is in [analysis.md](analysis.md).
- `analyze_session(laps, context)` combines the laps of a session into
  findings, the **one** next change, up to two alternatives, a verdict on the
  previous change (comparing with the session before it), and a list of things
  the telemetry cannot tell.

The rules it follows:

- Only valid flying laps count towards findings.
- A recommendation always names one setting, in the game's menu terms: section,
  setting, axle, direction and step, plus a target value when the current tune
  value is known.
- Settings that do not exist for the car's drivetrain are never recommended.
- When a conclusion depends on something Data Out does not send (tire pressure,
  temperature across the tread), the result says so.

When a lap is completed, the API pushes `lap_completed` and then
`analysis_ready` over the WebSocket so the UI can refresh without polling.

### Tunes

The game does not send the current tune, so the player enters it in Pitwall's
tune sheet, using the numbers and units shown in the game. A tune may be
partial. When the player marks a recommendation as applied, Pitwall creates a
new tune version with exactly that one value changed and makes it the active
tune. The chain of versions is the change history, and because every session
records the tune it was driven with, the next session can be compared with the
previous one to judge the change.

## Units

Frames keep the game's raw units: tire temperatures in °F, pedals 0 to 255,
steering −127 to 127, and so on. Conversion happens once, at the API boundary.
Everything the API returns uses m/s, °C, metres, seconds, radians, pedals 0..1
and steering −1..1. The UI converts for display according to the user's unit
settings (km/h or mph, °C or °F, psi or bar).

## Why raw packets are kept

Pitwall stores every recorded packet as the bytes it received, not just the
parsed and derived data:

- **The analysis will change.** Thresholds get tuned, metrics get added, bugs
  get fixed. With the raw packets, an old session can be analysed again by
  newer code instead of being stuck with what an older version computed.
- **Parsing can be wrong.** If a field turns out to be interpreted incorrectly,
  the fix can be applied to past recordings too.
- **Replay.** Recorded files can be played back with `python -m pitwall replay`
  to develop and test without the game.
- **It is cheap.** A Car Dash packet is 331 bytes and the game sends 60 per
  second: about 20 KB/s, roughly 70 MB per hour, and only while recording and
  on track.

The file format is described in [storage.md](storage.md).

## Data Out notes

- Packet format "Car Dash" ("Dash" in the official documentation): 331 bytes,
  little-endian, 60 packets per second. It is the Sled section (232 bytes),
  the Dash section (79 bytes), and two Forza Motorsport (2023) additions: tire
  wear for each wheel (4 × f32) and the track ID (s32).
- The race-on flag is 0 in menus and while paused.
- Rewinds make the current lap time and the distance travelled jump backwards.
- Not in the stream: tire pressure, temperature across the tread (one value per
  tire), the current tune, car and track names (numeric IDs only), lap
  validity.
- Official field list:
  [Forza Motorsport "Data Out" Documentation](https://support.forza.net/hc/en-us/articles/21742934024211-Forza-Motorsport-Data-Out-Documentation).

## Deployment

The Docker image runs the same process as an unprivileged user, receives
telemetry on 5300/udp, serves the UI and API on 5301/tcp, keeps its data in the
`/data` volume and reports healthy when `/api/status` answers. Pitwall is meant
for a local network and has no authentication. See [install.md](install.md).

## Further reading

- [install.md](install.md): installation, configuration, troubleshooting
- [api.md](api.md): REST and WebSocket reference
- [storage.md](storage.md): database schema and raw packet file format
- [data-out.md](data-out.md): packet layout and field notes
- [analysis.md](analysis.md): metrics, thresholds, rules and limits
