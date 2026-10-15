# Forza Motorsport Data Out

Pitwall reads the telemetry stream that Forza Motorsport (2023) sends over UDP
("Data Out"). This page covers the game setup and the packet layout Pitwall
expects. The layout was checked against the official
[Forza Motorsport "Data Out" documentation](https://support.forza.net/hc/en-us/articles/21742934024211-Forza-Motorsport-Data-Out-Documentation).

## Game setup

In the game: **Settings → Gameplay & HUD → "UDP Race Telemetry"**.

| Setting | Value |
|---|---|
| Data Out | On |
| Data Out IP Address | IP of the machine running Pitwall (`127.0.0.1` if it runs on the same PC) |
| Data Out IP Port | Pitwall's UDP port, `5300` by default (`PITWALL_UDP_PORT`) |
| Data Out Packet Format | **Dash** (sometimes labelled "Car Dash"). "Sled" lacks speed, laps and inputs. |

The game starts sending as soon as you are on track, 60 packets per second.
Make sure the firewall on the Pitwall machine allows incoming UDP on that port.
`GET /api/status` shows `receiver.packets_per_sec`; if packets arrive in the
wrong format, `receiver.ignored_packets` and `receiver.last_ignored_size` say so
(232 bytes means the game is set to "Sled").

## Packet sizes

| Size | Format | Pitwall |
|---|---|---|
| 331 B | Forza Motorsport (2023) Dash: Sled + Dash + FM2023 extras | parsed |
| 311 B | Forza Motorsport 7 Dash: Sled + Dash | parsed; tire wear reads 0, track ordinal is unknown |
| 232 B | Sled only | counted and ignored |
| 324 B | Forza Horizon 4/5 Dash | counted and ignored |
| anything else | | counted and ignored |

## Layout

Little-endian, no padding. Types: `S` signed integer, `U` unsigned integer,
`F` float, followed by the size in bits. Per-wheel fields come in the order
front-left, front-right, rear-left, rear-right (4 values each).

### Sled (bytes 0–231)

| Offset | Type | Field | Notes |
|---|---|---|---|
| 0 | S32 | IsRaceOn | 1 on track, 0 in menus or paused |
| 4 | U32 | TimestampMS | game clock, wraps around |
| 8 | F32 | EngineMaxRpm | |
| 12 | F32 | EngineIdleRpm | |
| 16 | F32 | CurrentEngineRpm | |
| 20 | F32 ×3 | AccelerationX/Y/Z | m/s², car space: X right, Y up, Z forward |
| 32 | F32 ×3 | VelocityX/Y/Z | m/s, car space |
| 44 | F32 ×3 | AngularVelocityX/Y/Z | rad/s; X pitch, Y yaw, Z roll |
| 56 | F32 ×3 | Yaw, Pitch, Roll | rad |
| 68 | F32 ×4 | NormalizedSuspensionTravel | 0 = max stretch, 1 = max compression |
| 84 | F32 ×4 | TireSlipRatio | normalized: 0 = full grip, \|x\| > 1 = grip lost |
| 100 | F32 ×4 | WheelRotationSpeed | rad/s |
| 116 | S32 ×4 | WheelOnRumbleStrip | 1 on a rumble strip |
| 132 | F32 ×4 | WheelInPuddleDepth | 0..1 |
| 148 | F32 ×4 | SurfaceRumble | force-feedback value |
| 164 | F32 ×4 | TireSlipAngle | normalized: 0 = full grip, \|x\| > 1 = grip lost |
| 180 | F32 ×4 | TireCombinedSlip | normalized: 0 = full grip, \|x\| > 1 = grip lost |
| 196 | F32 ×4 | SuspensionTravelMeters | m |
| 212 | S32 | CarOrdinal | car model id (no names in the stream) |
| 216 | S32 | CarClass | class index, see below |
| 220 | S32 | CarPerformanceIndex | 100..999 |
| 224 | S32 | DrivetrainType | 0 FWD, 1 RWD, 2 AWD |
| 228 | S32 | NumCylinders | |

### Dash (bytes 232–310)

| Offset | Type | Field | Notes |
|---|---|---|---|
| 232 | F32 ×3 | PositionX/Y/Z | m, world space |
| 244 | F32 | Speed | m/s |
| 248 | F32 | Power | W |
| 252 | F32 | Torque | N·m |
| 256 | F32 ×4 | TireTemp | °F, one value per tire |
| 272 | F32 | Boost | |
| 276 | F32 | Fuel | 0..1 |
| 280 | F32 | DistanceTraveled | m, goes backwards on rewind |
| 284 | F32 | BestLap | s, 0 = none yet |
| 288 | F32 | LastLap | s, 0 = none yet |
| 292 | F32 | CurrentLap | s, goes backwards on rewind |
| 296 | F32 | CurrentRaceTime | s |
| 300 | U16 | LapNumber | 0 on the first lap |
| 302 | U8 | RacePosition | |
| 303 | U8 | Accel | throttle 0..255 |
| 304 | U8 | Brake | 0..255 |
| 305 | U8 | Clutch | 0..255 |
| 306 | U8 | HandBrake | 0..255 |
| 307 | U8 | Gear | see below |
| 308 | S8 | Steer | −127..127 |
| 309 | S8 | NormalizedDrivingLine | −127..127 |
| 310 | S8 | NormalizedAIBrakeDifference | −127..127 |

### Forza Motorsport (2023) additions (bytes 311–330)

| Offset | Type | Field | Notes |
|---|---|---|---|
| 311 | F32 ×4 | TireWear | 0..1 |
| 327 | S32 | TrackOrdinal | track layout id (no names in the stream) |

## Encodings the official page doesn't spell out

- **Gear**: `0` = reverse, `1`–`10` = forward gears, `11` = neutral. This is the
  encoding community tools observe; the official page only lists the field.
  The API turns it into `-1` reverse, `0` neutral, `1..10` forward.
- **Car class**: the official page still describes the Forza Motorsport 7 range
  (0 = D … 7 = X). Forza Motorsport (2023) has nine classes, and community tools
  map the index as 0 = E, 1 = D, 2 = C, 3 = B, 4 = A, 5 = S, 6 = R, 7 = P, 8 = X.
  Pitwall reports the raw index and derives the class letter from the
  performance index instead: E ≤ 300, D ≤ 400, C ≤ 500, B ≤ 600, A ≤ 700,
  S ≤ 800, R ≤ 900, P ≤ 998, X = 999.
- **Tire wear**: the direction of the scale is not documented. Pitwall passes
  the value through unchanged.

## What the stream does not contain

- Tire pressure, and tire temperature across the tread (one value per tire, so
  camber can't be judged from it).
- The current tune. Pitwall's tune sheet is entered by the player.
- Car and track names: only numeric ordinals.
- Lap validity (track limits). Pitwall only knows about rewinds, pauses and
  data gaps.

## Behaviour worth knowing

- `IsRaceOn` is 0 in menus and while paused; Pitwall doesn't record those
  packets.
- A rewind makes `CurrentLap` and `DistanceTraveled` jump backwards, and can
  move `LapNumber` back by one if it crosses the line.
- `LastLap` updates when the car crosses the line, sometimes a frame or two
  after `LapNumber` changes; Pitwall waits for it.
