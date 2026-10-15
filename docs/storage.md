# Storage

Everything lives in one directory, `PITWALL_DATA_DIR` (default `./data`):

```
data/
  pitwall.db              SQLite database (plus pitwall.db-wal / -shm while running)
  raw/
    session-1.pitwall     raw packets of session 1
    session-2.pitwall
```

To back up, stop Pitwall and copy the directory. Deleting a session through the
API removes its rows and its raw file.

## Raw packet files

Every packet recorded in a session is kept exactly as received, so laps can be
re-analysed later with better algorithms, or replayed with
`python -m pitwall replay data/raw/session-N.pitwall`.

A `.pitwall` file is a gzip stream. Decompressed, it is:

```
magic   8 bytes   b"PWRAW002"  (b"PWRAW001" in files from older versions)
record* repeated until the end:
  recv_time  f64 little-endian   receive time, seconds (host monotonic clock)
  length     u16 little-endian   payload size in bytes
  payload    length bytes        the UDP datagram, unchanged
```

- Only the differences between `recv_time` values mean anything; the absolute
  value is the receiving machine's monotonic clock. The session's wall-clock
  start time is in the database.
- All packets with `IsRaceOn = 1` are recorded, plus one race-off packet each
  time the game leaves the race (menu, pause, rewind screen, finish). These
  markers let `reindex` cut laps exactly as they were cut live. Version 1 files
  have no markers.
- Records are numbered from 0 in file order. Each lap points at its records
  with `first_frame` and `last_frame` (inclusive); markers and pre-race packets
  inside that range are not part of the lap.
- The writer flushes the compressor about once per second and after every lap.
  If Pitwall is killed mid-session, the file is readable up to the last flush,
  and readers stop quietly at a truncated tail.

Python example:

```python
from pitwall.storage.rawlog import iter_records
from pitwall.telemetry.packet import parse

frames = [parse(payload, t) for t, payload in iter_records(path)]
```

## Database

SQLite, schema version in `PRAGMA user_version` (currently 2; a version 1
database is upgraded on start). Timestamps are
UTC ISO-8601 strings with milliseconds (`2026-01-31T18:04:05.123Z`).

### `sessions`

One row per recording (Start → Stop).

| Column | Meaning |
|---|---|
| `id` | |
| `started_at`, `stopped_at` | wall clock; `stopped_at` is null while recording |
| `car_ordinal`, `car_pi`, `car_class`, `drivetrain` | from the first recorded packet; `drivetrain` is `FWD`/`RWD`/`AWD` |
| `track_ordinal` | null for Forza Motorsport 7 packets |
| `note` | free text |
| `raw_file` | path of the raw packet file, relative to the data directory |
| `frame_count` | packets recorded |

Sessions left open by a crash are closed (with the restart time as
`stopped_at`) the next time Pitwall starts.

### `laps`

| Column | Meaning |
|---|---|
| `id`, `session_id` | |
| `number` | lap number as on the game HUD (the packet's `LapNumber` + 1) |
| `lap_time` | seconds, from `LastLap` after the line; null if the lap wasn't finished |
| `kind` | `out`, `flying`, `in` or `partial` (rules below) |
| `valid` | 0/1 |
| `invalid_reason` | `rewind`, `pause`, `data_gap` or `partial`; null when valid |
| `frame_count` | packets in the lap |
| `first_frame`, `last_frame` | the lap's record range in the raw file (inclusive) |
| `started_at` | wall clock of the lap's first packet |

### `kv`

Small JSON values: `settings` (units, auto-record).

### `analysis_cache`

Results of lap and session analysis as JSON, keyed by `(kind, ref_id)` with a
fingerprint of everything the result depends on (engine version, unit
system, laps). A result whose fingerprint no longer matches is recomputed
on the next request, so the cache can be deleted at any time.

## How laps are cut

The recorder feeds every race-on packet to a lap segmenter and tells it about
race-off packets. Nothing depends on the packet rate: the game sends 60 packets
per second on console and 120–160 on PC.

- **Pre-race**: before the start the lap timer (`CurrentLap`) reads exactly 0.
  Those packets belong to no lap.
- **Line crossings**: a lap ends when `LapNumber` goes up. After a grid start
  the car crosses the start line once before lap 1 is timed: the game restarts
  the lap timer there without changing `LapNumber`. That restart counts as a
  crossing, and the few seconds of run-up from the grid before it are not
  stored as a lap.
- **Race finish**: at the chequered flag the game switches `IsRaceOn` off
  instead of increasing `LapNumber`. If the car is within 20 m of where the
  line should be (lap length from an earlier lap, or from the pre-race
  packets, whose distance reads minus one lap), the lap is complete.
- **Lap time** is the `LastLap` value once the game updates it after the line.
  If it doesn't change within 0.5 s, the last lap-timer value before the line
  is used. A lap that ended at the finish uses the last lap-timer value plus
  the time to cover the remaining metres.
- **Kind**
  - `partial`: the lap's start wasn't seen (recording started mid-lap, or a
    rewind dropped the car back into the previous lap), or it ended away from
    the line at speed (quitting the event, stopping the recording).
  - `out`: complete lap that started from (nearly) standstill (< 10 m/s), such
    as leaving the pits.
  - `flying`: complete lap that started at speed, including the first lap of a
    race (timing starts at the line, at speed).
  - `in`: started at the line, not finished, car nearly stopped (< 5 m/s) at
    the end, as when driving into the pits.
- **Validity**, first reason found wins:
  - `rewind`: the race clock or lap timer goes back by more than 0.05 s, or
    `DistanceTraveled` by more than 5 m. A rewind also sends race-off packets
    (the rewind screen); going backwards decides it is a rewind, not a pause.
  - `pause`: race-off packets in the middle of the lap, then the race carries
    on where it was.
  - `data_gap`: no packets for more than 1 s.
  - `partial`: see above.
- Incomplete laps shorter than one second are dropped.

## Rebuilding laps: `reindex`

After an update that changes how laps are cut or analysed, rebuild existing
recordings from their raw packet files:

```
python -m pitwall reindex                 # all sessions, then re-run the analysis
python -m pitwall reindex --session 3     # one session (repeatable)
python -m pitwall reindex --dry-run       # print before/after lap tables only
python -m pitwall reindex --no-analysis   # laps only
```

It uses `PITWALL_DATA_DIR` (or `--data-dir`), skips sessions still being
recorded, and replaces each session's laps and cached analysis in one
transaction. Lap ids change. For version 1 raw files, which have no race-off
markers, a gap of more than 1 s between race-on packets is read as the game
leaving the race. It can run while the server is up; restart the server
afterwards so it forgets laps it holds in memory.

Auto-record (`settings.auto_record`): a session starts when `IsRaceOn` goes
from 0 to 1, and an automatically started session stops after 30 s without
race-on packets. Manually started sessions are only stopped manually.
