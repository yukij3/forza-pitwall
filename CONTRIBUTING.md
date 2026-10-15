# Contributing

Bug reports, fixes and improvements are welcome. For anything larger than a
small fix, open an issue first so the approach can be agreed before you spend
time on it.

## Setup

You need Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                          # creates .venv with runtime and dev dependencies
uv run python -m pitwall serve   # UDP 5300, web UI on http://localhost:5301
uv run python -m pitwall simulate  # synthetic telemetry, no game needed
```

The UI also has a demo mode that fakes the API and the live feed in the
browser: open `http://localhost:5301/?mock=1`.

## Tests and lint

```bash
uv run pytest
uv run ruff check .
```

CI runs both on every pull request, plus a Docker image build. Please add or
update tests with your change. Tests live in `tests/<area>/`, next to the other
tests for the module you touched.

## Style

- Python 3.12, formatted and linted with ruff (line length 100, rules in
  `pyproject.toml`).
- Standard library first. A new runtime dependency needs a good reason, because
  it ends up in every user's image; mention it in the pull request.
- Code, comments, UI text and docs in English.
- Use the game's exact English tuning-menu names (`Anti-roll Bars`, `Rebound
  Stiffness`, ...) in anything the user reads.
- Do not commit recordings, databases, IP addresses or other personal data.
  `data/` is gitignored for that reason.

## Module boundaries

- `pitwall/telemetry/model.py` (`Frame`) and `pitwall/tune/settings.py` (tune
  setting keys and in-game names) are shared by every module. Change them only
  deliberately, in their own pull request, and update all users.
- `pitwall/analysis/` is pure Python: it takes frames and context in and returns
  dataclasses out. No I/O, no global state, no imports from `api` or `storage`.
  Bump `pitwall.analysis.__version__` when results change, so cached analyses
  are recomputed.
- `pitwall/baselines/` is pure Python over bundled JSON in
  `pitwall/baselines/data/`. `cars.json` is derived from an MIT-licensed list;
  keep `cars.LICENSE.txt` next to it (see
  [docs/baselines.md](docs/baselines.md)).
- `pitwall/services/` connects storage, analysis and the API: the recorder, the
  live board and analysis runners, and the `Services` container the API
  routes use.
- Frames keep the game's raw units. Conversion to the API's units (m/s, °C, m,
  s, rad) happens at the API boundary, not in the model or the analysis.
- `pitwall/storage/` owns the database and raw packet files. Other modules go
  through it rather than touching files directly.
- `web/` is plain HTML, CSS and JavaScript (ES modules) with no build step and
  no CDN at runtime, because the LAN it runs on may be offline. Vendor any
  third-party file with its license. Keep demo mode (`?mock=1`) working.

See [docs/architecture.md](docs/architecture.md) for how the modules fit
together.

## Pull requests

- Keep each pull request to one topic.
- Describe what changed and how you tested it. For analysis changes, say which
  laps or synthetic cases you checked against.
- By contributing you agree that your work is released under the
  [MIT License](LICENSE).
