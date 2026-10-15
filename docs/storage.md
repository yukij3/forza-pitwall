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
magic   8 bytes   b"PWRAW001"
record* repeated until the end:
  recv_time  f64 little-endian   receive time, seconds (host monotonic clock)
  length     u16 little-endian   payload size in bytes
  payload    length bytes        the UDP datagram, unchanged
```

- Only the differences between `recv_time` values mean anything; the absolute
  value is the receiving machine's monotonic clock. The session's wall-clock
  start time is in the database.
- Only packets with `IsRaceOn = 1` are recorded.
- Records are numbered from 0 in file order. Each lap points at its records
  with `first_frame` and `frame_count`.
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

SQLite, schema version in `PRAGMA user_version` (currently 1). Timestamps are
UTC ISO-8601 strings with milliseconds (`2026-01-31T18:04:05.123Z`).

### `sessions`

One row per recording (Start → Stop).

| Column | Meaning |
|---|---|
| `id` | |
| `started_at`, `stopped_at` | wall clock; `stopped_at` is null while recording |
| `car_ordinal`, `car_pi`, `car_class`, `drivetrain` | from the first recorded packet; `drivetrain` is `FWD`/`RWD`/`AWD` |
| `track_ordinal` | null for Forza Motorsport 7 packets |
| `tune_id` | active tune when the recording started (editable) |
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
| `frame_count`, `first_frame` | the lap's records in the raw file |
| `started_at` | wall clock of the lap's first packet |

### `tunes`

Immutable tune versions. A new version is a new row with `parent_id` pointing
at the version it was derived from.

| Column | Meaning |
|---|---|
| `id`, `name`, `car_ordinal`, `note`, `created_at` | |
| `unit_system` | `imperial` or `metric`: the units the values were entered in |
| `values_json` | `{"arb.front": 18.0, ...}`, keys from `pitwall/tune/settings.py` |
| `parent_id` | previous version or null |
| `changes_json` | `[{"setting", "from", "to"}]`: diff against the parent, computed on save |

### `kv`

Small JSON values: `settings` (units, auto-record) and `active_tune_id`.

### `analysis_cache`

Results of lap and session analysis as JSON, keyed by `(kind, ref_id)` with a
fingerprint of everything the result depends on (engine version, tune, laps,
previous session). A result whose fingerprint no longer matches is recomputed
on the next request, so the cache can be deleted at any time.

## How laps are cut

The recorder feeds every recorded packet to a lap segmenter:

- A lap ends when `LapNumber` changes. Going up means the car crossed the line.
  Going down means a rewind (or restart) took the car back across it.
- **Lap time** is the `LastLap` value once the game updates it after the line
  (it can lag a frame or two). If it doesn't change within 30 packets, the last
  `CurrentLap` before the line is used.
- **Kind**
  - `partial`: the lap's start wasn't seen (recording started mid-lap, or a
    rewind dropped the car back into the previous lap), or the recording
    stopped mid-lap at speed.
  - `out`: complete lap that started from (nearly) standstill (< 10 m/s), such
    as a standing start or leaving the pits.
  - `flying`: complete lap that started at speed.
  - `in`: started at the line, not finished, and ended in the menus or with the
    car nearly stopped (< 5 m/s).
- **Validity**: a lap is invalid if `CurrentLap` goes back by more than 0.05 s
  or `DistanceTraveled` by more than 5 m (`rewind`), if race-off packets
  arrived in the middle of it (`pause`), if no packet arrived for more than 1 s
  (`data_gap`), or if it is `partial`. The first reason found is stored.
- An unfinished lap shorter than one second at Stop is dropped.

Auto-record (`settings.auto_record`): a session starts when `IsRaceOn` goes
from 0 to 1, and an automatically started session stops after 30 s without
race-on packets. Manually started sessions are only stopped manually.
