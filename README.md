# Pitwall

Telemetry recorder and tuning assistant for Forza Motorsport (2023).

Pitwall listens to the game's Data Out telemetry, records your stints and turns
the data into one tuning change at a time, worded the way the game's tuning menu
words it: `Differential → Acceleration (Rear): −5%`. After you apply the change
and drive again, it compares the laps and tells you whether the change helped.
It is for Forza Motorsport players who tune their own cars and want a concrete
next step rather than a wall of graphs. It runs in Docker on your PC or a home
server, and you keep it open in a browser on a second screen.

<!--
  SCREENSHOT PLACEHOLDER
  Add a real screenshot of the Live and Analysis screens here, for example:
  ![Pitwall analysis screen](docs/images/analysis.png)
  If it was taken in simulator or mock mode, say so in the caption.
-->

> **Status:** early development (0.1). The API and the stored data format may
> still change between versions.

## How a tuning session works

1. **Drive a stint.** Start recording in Pitwall (or turn on auto-record) and
   drive a few clean laps, typically 3 to 5.
2. **Read one change.** Pitwall analyses the valid flying laps and shows the
   single change it would make next, in game-menu terms, with the evidence behind
   it and how confident it is. Up to two alternatives are listed in case you want
   to try something else.
3. **Apply it.** Make the change in the game's tuning menu and mark it as applied
   in Pitwall. Pitwall saves a new version of your tune with that one value
   changed.
4. **Verify.** Drive the next stint. Pitwall compares it with the previous one
   and reports whether the change helped: lap time, and the handling problem it
   was meant to fix.

Then repeat. One change per stint keeps cause and effect clear.

## Features

- **Live view** for a second screen, readable at a glance while driving: speed,
  gear, rpm, inputs, lap times and tire state.
- **Recording** started and stopped from the browser, or optionally started
  automatically when you go on track. Laps are split and labelled (out, flying,
  in); laps with a rewind or a pause are marked invalid.
- **Lap analysis** with metrics such as corner balance on entry, mid-corner and
  exit, wheelspin, lockups, bottoming out, time on the rev limiter, and tire
  temperatures and wear. Each finding shows the evidence behind it.
- **One recommendation at a time**, named exactly as in the tuning menu
  (section, setting, axle, direction, amount), and only for settings that exist
  for the car's drivetrain.
- **Tune sheet** in the game's menu order, with a history of every change.
- **Raw packets are kept** with each recording, so recordings stay useful when
  the analysis changes.
- **Self-contained**: one container, SQLite, no accounts, no cloud services, no
  internet connection needed at runtime.

## Quick start (Docker Compose)

You need Docker with Compose v2 on a machine in the same local network as the
device running the game. That can be the gaming PC itself.

```bash
git clone https://github.com/OWNER/forza-pitwall.git
cd forza-pitwall
mkdir -p data
```

Open `compose.yaml` and set `PITWALL_PUBLIC_HOST` to the LAN IP address of this
machine (for example `192.168.1.20`; `ipconfig` on Windows, `ip -4 addr` on
Linux). Then start it:

```bash
docker compose up -d --build
```

Open `http://<that IP>:5301` in a browser. The database and recordings are
stored in `./data`.

Pitwall receives telemetry on UDP port 5300 and serves the web UI on TCP port
5301. Both can be changed; see [docs/install.md](docs/install.md).

## Set up Data Out in the game

In Forza Motorsport, open **Settings → Gameplay & HUD** and scroll down to the
**UDP Race Telemetry** section:

| Option | Value |
|---|---|
| Data Out | On |
| Data Out IP Address | the LAN IP of the machine running Pitwall |
| Data Out IP Port | 5300 |
| Data Out Packet Format | Car Dash ("Dash" in the official documentation) |

If Pitwall runs on the same PC as the game, `127.0.0.1` also works.

The game starts sending once you are on track. In menus and while paused it
reports that no race is running, and Pitwall does not record those frames. If
the UI shows no packets while you are driving, see
[Troubleshooting](docs/install.md#troubleshooting-no-packets).

## Running on a home server or NAS

An always-on box is a good place for Pitwall: the game sends telemetry to it
over the network, and you open the UI from any device on the LAN. Publish
5300/udp and 5301/tcp, map a persistent folder to `/data` and set
`PITWALL_PUBLIC_HOST` to the server's IP. [docs/install.md](docs/install.md)
covers `docker run`, Unraid-style container templates, file permissions and
firewalls.

Pitwall has no login. Keep it on your local network and do not forward its
ports to the internet.

## What Data Out cannot see

Pitwall only knows what the game sends, and some things that matter for tuning
are not in the stream:

- **Tire pressure.** Not sent at all.
- **Temperature across the tread.** The game sends one temperature per tire,
  not inner, middle and outer, so camber cannot be judged from telemetry. Use
  the game's own telemetry screens for pressure and camber.
- **Your current tune.** Pitwall cannot read it. Enter the values in the tune
  sheet; without them, a recommendation gives a direction and a step instead of
  a target value.
- **Car and track names.** Only numeric IDs are sent.
- **Lap validity.** Track-limit penalties are not reported. Pitwall can only
  detect rewinds and pauses.

Where these gaps affect a recommendation, Pitwall says so instead of guessing.

## Development

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                          # dependencies, including dev tools
uv run pytest                    # tests
uv run ruff check .              # lint
uv run python -m pitwall serve   # UDP 5300, web UI on http://localhost:5301
```

To try Pitwall without the game, run the simulator in a second terminal while
the server is running. It generates synthetic Data Out telemetry:

```bash
uv run python -m pitwall simulate
```

`python -m pitwall replay <file>` plays back a recorded packet file. The web UI
also has a mock mode, `http://localhost:5301/?mock=1`, that fakes the API and
the live feed, for working on the UI alone.

See [CONTRIBUTING.md](CONTRIBUTING.md) for code style and module boundaries, and
[docs/architecture.md](docs/architecture.md) for how the parts fit together.

## Project layout

```
pitwall/
  telemetry/    Data Out packet format, UDP receiver, lap splitting, Frame model
  storage/      SQLite database and raw packet files
  analysis/     lap metrics, handling diagnosis, recommendations (no I/O)
  api/          REST and WebSocket API (FastAPI)
  tune/         tune settings in the game's menu order, with in-game names
  tools/        simulator and replay
  app.py        application wiring
  config.py     configuration from environment variables
  __main__.py   command line: serve, simulate, replay
web/            browser UI: plain HTML, CSS and JavaScript, no build step
tests/          pytest suites, one folder per area
docs/           installation, architecture, API, storage and analysis notes
```

## Disclaimer

Pitwall is an independent fan project. It is not affiliated with, endorsed by or
sponsored by Microsoft, Turn 10 Studios or Playground Games. Forza and Forza
Motorsport are trademarks of Microsoft Corporation and are used here only to
describe what the software works with.

## License

[MIT](LICENSE)
