# HTTP and WebSocket API

Pitwall serves a JSON API under `/api`, a live WebSocket at `/ws/live`, and the
web UI at `/`. The default port is `5301` (`PITWALL_HTTP_PORT`). Interactive
OpenAPI docs are at `/api/docs` (schema at `/api/openapi.json`).

There is no authentication: Pitwall is meant for a home LAN.

## Conventions

- **Units.** Everything the API returns uses: speed m/s, temperature °C,
  distance m, time s, angles rad, pedals 0..1, steering −1..1 (negative =
  left), accelerations in g. Slip values are the game's normalized numbers
  (0 = full grip, above 1 = grip lost). The UI converts for display using
  `/api/settings`.
- **Lap numbers** are 1-based, as on the game HUD.
- **Gear**: `-1` reverse, `0` neutral, `1`..`10` forward.
- **Timestamps**: UTC ISO-8601 with milliseconds, e.g. `2026-01-31T18:04:05.123Z`.
- **Errors** always look like this, with a 4xx/5xx status:

  ```json
  {"error": {"code": "not_found", "message": "session 7 not found"}}
  ```

| Code | Status | When |
|---|---|---|
| `not_found` | 404 | unknown id, or no endpoint for this `/api` path and method |
| `validation_error` | 422 | malformed body or query parameter |
| `already_recording` | 409 | start while a recording runs |
| `not_recording` | 409 | stop while nothing records |
| `session_recording` | 409 | delete the session that is being recorded |
| `analysis_unavailable` | 503 | the analysis engine isn't installed |
| `baselines_unavailable` | 503 | the baseline setups module isn't installed |
| `analysis_failed` | 500 | the analysis engine raised an error |

## Status

### `GET /api/status`

```json
{
  "receiver": {
    "listening": true,
    "udp_port": 5300,
    "public_host": "192.0.2.10",
    "packets_per_sec": 60.0,
    "last_packet_age_s": 0.02,
    "race_on": true,
    "ignored_packets": 0,
    "last_ignored_size": null
  },
  "recording": {"active": true, "session_id": 12, "started_at": "2026-01-31T18:04:05.123Z", "laps": 3},
  "car": {"ordinal": 1234, "name": "2014 Mazda #70 SpeedSource Lola B12/80",
          "division": "Forza P2", "class": 7, "class_name": "P", "pi": 949,
          "drivetrain": "RWD"},
  "track_ordinal": 860
}
```

- `public_host` is `PITWALL_PUBLIC_HOST` (null if unset): the address to enter
  in the game's Data Out settings.
- `last_packet_age_s` is null until the first packet arrives. `race_on` is
  false when the last packet is a menu/pause packet or is older than 2 s.
- `ignored_packets` counts datagrams of an unsupported size;
  `last_ignored_size` is the size of the last one (232 = game set to "Sled").
- `car` and `track_ordinal` come from the last race-on packet, so they survive
  trips to the menu; both are null before the first one. `name` and
  `division` come from the baseline setups' car list and are null for cars it
  doesn't know (or when that module isn't installed). `class` is the raw
  class index from the packet; `class_name` is derived from the performance
  index (see [data-out.md](data-out.md)). `track_ordinal` is null for
  Forza Motorsport 7 packets.
- `recording.laps` is the number of laps stored in the active session (0 when
  not recording).

## Recording

### `POST /api/recording/start`

Body (optional): `{"note": "Wet practice"}`. Returns the new **Session**. 409
`already_recording` if one is running. Car and track fields fill in when the
first race-on packet arrives.

### `POST /api/recording/stop`

Returns the finished **Session**. 409 `not_recording` if nothing records. The
lap in progress is closed (see [storage.md](storage.md) for how laps are cut).
Shutting Pitwall down stops an active recording the same way.

## Sessions

**Session**

```json
{
  "id": 12,
  "started_at": "2026-01-31T18:04:05.123Z",
  "stopped_at": "2026-01-31T18:20:41.002Z",
  "car_ordinal": 1234, "car_pi": 949, "car_class": 7, "car_class_name": "P",
  "drivetrain": "RWD",
  "track_ordinal": 860,
  "note": "",
  "lap_count": 6,
  "best_lap": 97.912,
  "recording": false
}
```

`best_lap` is the fastest valid flying lap (null if none). `recording` is true
for the session being recorded. Car fields are null if no race-on packet was
recorded.

### `GET /api/sessions`

All sessions, newest first.

### `GET /api/sessions/{id}`

The session plus `"laps": [Lap]` in recording order.

### `PATCH /api/sessions/{id}`

Body: `{"note": string}`. Returns the session.

### `DELETE /api/sessions/{id}`

204 on success. Deletes the laps, cached analysis and the raw packet file. 409
`session_recording` for the session being recorded.

### `GET /api/sessions/{id}/analysis`

The analysis engine's **SessionAnalysis** for the session (shape owned by the
engine, see `docs/analysis.md`). It is computed on request from the session's
laps and cached until the laps or the unit setting change. 503
`analysis_unavailable` without the engine.

v1 doesn't track tunes, so the engine gets no tune values, tune changes or
previous session: `suggested_value` and `verdict_on_last_change` are always
null.

## Laps

**Lap**

```json
{
  "id": 57, "session_id": 12, "number": 3,
  "lap_time": 97.912,
  "kind": "flying",
  "valid": true, "invalid_reason": null,
  "frame_count": 5875,
  "started_at": "2026-01-31T18:07:22.480Z"
}
```

- `kind`: `out` | `flying` | `in` | `partial`.
- `invalid_reason`: `rewind` | `pause` | `data_gap` | `partial` | null.
- `lap_time` is null for laps that didn't reach the line.

### `GET /api/laps/{id}`

The lap plus `"metrics"`: the **LapMetrics** from the lap analysis, or null when
the analysis engine isn't available.

### `GET /api/laps/{id}/trace?hz=20`

The lap resampled to `hz` samples per second (0 < hz ≤ 60, default 20), as
parallel arrays:

```json
{"hz": 20, "t": [], "distance": [], "speed": [], "throttle": [], "brake": [],
 "steer": [], "gear": [], "rpm": [], "lat_g": [], "lon_g": [],
 "slip_angle_front": [], "slip_angle_rear": [], "slip_ratio_rear": [],
 "susp_front": [], "susp_rear": [], "pos_x": [], "pos_z": []}
```

- `t`: seconds into the lap, on the game clock (starts at the lap timer's value
  on the first packet, ~0 for laps recorded from the line).
- `distance`: metres since the lap's first packet.
- `slip_angle_front` / `slip_angle_rear` / `slip_ratio_rear`: axle mean of the
  absolute normalized slip values.
- `susp_front` / `susp_rear`: axle mean of normalized suspension travel
  (0 = full extension, 1 = full compression).
- `pos_x` / `pos_z`: world position in metres (for a track map).
- Continuous channels are linearly interpolated; `gear` is the gear of the
  preceding packet.

### `GET /api/laps/{id}/analysis`

The engine's **LapAnalysis** for the lap. Laps are analysed in the background as
soon as they finish (see `analysis_ready` below); results are cached. 503
`analysis_unavailable` without the engine.

## Setup reference

### `GET /api/tune-schema`

Every tuning setting in the game's menu order, for labels:

```json
[{"key": "arb.front", "section": "Anti-roll Bars", "label": "Anti-roll Bars",
  "axle": "Front", "unit_imperial": "", "unit_metric": "",
  "drivetrains": ["FWD", "RWD", "AWD"]}]
```

## Baseline setups

Approximate starting setups per car type, with sources and a confidence level.
The data and the shapes below (**Category**, **Match**, **Baseline**) come from
the baseline setups module; without it, these endpoints answer 503
`baselines_unavailable`.

Each endpoint takes an optional `unit_system` query parameter (`imperial` |
`metric`). Without it, the unit system follows the speed setting (`mph` →
imperial, `kmh` → metric).

### `GET /api/baseline/categories`

All categories:

```json
[{"id": "lmp2", "name": "LMP2 / Forza P2 prototypes", "description": "...",
  "divisions": ["Forza P2"], "drivetrains": ["RWD"]}]
```

### `GET /api/baseline`

The best match for the car currently on track (the car in `/api/status`) and its
baseline:

```json
{"match": {"category_id": "lmp2", "how": "ordinal", "confidence": "high",
           "car": {"ordinal": 1234, "name": "2014 Mazda #70 SpeedSource Lola B12/80",
                   "division": "Forza P2"}},
 "baseline": Baseline}
```

`how` is `ordinal` (the car is known), `division` or `class_drivetrain`
(guessed from class and drivetrain). Both fields are null when no car has been
seen yet or nothing matches.

### `GET /api/baseline/{category_id}`

The **Baseline** for a category picked by hand; 404 `not_found` for an unknown
id.

```json
{"category": Category, "unit_system": "imperial",
 "settings": [{"key": "arb.front", "section": "Anti-roll Bars", "label": "Anti-roll Bars",
               "axle": "Front", "value": 18.0, "range": [15.0, 22.0],
               "unit": "", "relative": null, "note": "..."}],
 "notes": ["..."], "sources": [{"title": "...", "url": "..."}],
 "confidence": "low"}
```

## Settings

### `GET /api/settings`

```json
{"units": {"speed": "kmh", "temperature": "C", "pressure": "bar"},
 "auto_record": false}
```

### `PUT /api/settings`

Partial updates are fine: `{"units": {"speed": "mph"}}`. Allowed values:
`speed` `kmh`|`mph`, `temperature` `C`|`F`, `pressure` `psi`|`bar`. Returns the
full settings.

With `auto_record` on, a session starts when the game goes on track
(`IsRaceOn` 0 → 1) and stops after 30 s without race-on packets. Turning it on
while already on track starts a session with the next packet.

## Live tuning board

A rolling analysis of the last few corners, fed with every race-on packet
whether or not a session is recording. The snapshot shape (**LiveAnalysis**) is
owned by the analysis engine, see `docs/analysis.md`:

```json
{"corners_seen": 23, "window": {"corners": 12, "laps": 1.7},
 "focus": "mid_balance_low",
 "items": [{"id": "mid_balance_low", "group": "Balance", "title": "Mid-corner, slow corners",
            "status": "warn", "value": 0.18, "value_text": "Understeer 0.18",
            "target_text": "−0.05 … +0.10", "samples": 9, "recommendation": null}]}
```

The board starts over automatically when the car or track changes, using the
car's drivetrain. Recommendation units follow the speed setting (`mph` →
imperial, `kmh` → metric).

### `GET /api/live-analysis`

The current LiveAnalysis. 503 `analysis_unavailable` without the engine.

### `POST /api/live-analysis/reset`

Starts the board over; press it after changing the setup in game. Returns the
fresh LiveAnalysis. 503 `analysis_unavailable`
without the engine.

## WebSocket `/ws/live`

Server → client JSON messages; the client doesn't need to send anything.

### `status`

```json
{"type": "status", ...Status}
```

Sent on connect, whenever something important changes (recording, race on/off,
packets starting or stopping, car, track), and at least once per
second.

### `telemetry`

Sent at `PITWALL_LIVE_HZ` (default 20 per second) while packets arrive, always
with the newest packet:

```json
{"type": "telemetry", "t": 12.35, "speed": 61.2, "rpm": 7450.0, "max_rpm": 9000.0,
 "gear": 4, "throttle": 1.0, "brake": 0.0, "steer": -0.12,
 "lap_number": 3, "current_lap": 41.2, "last_lap": 98.7, "best_lap": 97.9,
 "race_position": 1, "lat_g": 1.8, "lon_g": -0.2,
 "tire_temp": {"fl": 88.1, "fr": 90.3, "rl": 92.0, "rr": 93.4},
 "tire_wear": {"fl": 0.98, "fr": 0.98, "rl": 0.97, "rr": 0.97},
 "slip_angle": {"fl": 0.6, "fr": 0.6, "rl": 0.4, "rr": 0.4},
 "slip_ratio": {"fl": 0.1, "fr": 0.1, "rl": 0.2, "rr": 0.2},
 "susp": {"fl": 0.52, "fr": 0.48, "rl": 0.45, "rr": 0.44},
 "pos": {"x": 120.4, "z": -33.0}}
```

- `t`: receive time in seconds since the server started (monotonic).
- `last_lap` / `best_lap`: null until the game has one.
- `lat_g` = lateral acceleration / 9.81 (positive to the right), `lon_g` =
  longitudinal acceleration / 9.81 (positive = accelerating).
- `tire_temp` in °C; `slip_angle` / `slip_ratio` signed normalized values;
  `susp` normalized travel 0..1.
- Menu/pause packets are sent too (mostly zeros); check `status.receiver.race_on`.

### `lap_completed`

```json
{"type": "lap_completed", "session_id": 12, "lap": Lap}
```

Sent when a recorded lap is stored (including the last, unfinished lap at Stop).

### `analysis_ready`

```json
{"type": "analysis_ready", "session_id": 12, "lap_id": 57}
```

Sent when the background analysis of a lap finishes. Fetch it with
`GET /api/laps/{id}/analysis`. Not sent without the analysis engine.

### `live_analysis`

```json
{"type": "live_analysis", ...LiveAnalysis}
```

Sent on connect and whenever the board changes, at most twice per second. Not
sent without the analysis engine.

Slow clients don't hold the server up: each connection has a bounded queue and
the oldest messages are dropped when it is full.
