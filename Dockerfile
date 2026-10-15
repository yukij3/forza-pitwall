# Pitwall container image.
#
#   docker build -t forza-pitwall .
#   docker run -p 5300:5300/udp -p 5301:5301 -v "$PWD/data:/data" forza-pitwall
#
# Two stages: the first resolves runtime dependencies from uv.lock into a
# virtualenv, the second copies that virtualenv and the application source onto
# a clean python:3.12-slim, without uv or any build tooling.

# ---------------------------------------------------------------------------
# Stage 1: dependencies
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS deps

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Only the lock and project metadata, so this layer is rebuilt only when
# dependencies change. --locked fails the build if uv.lock is out of date.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim

LABEL org.opencontainers.image.title="forza-pitwall" \
      org.opencontainers.image.description="Forza Motorsport Data Out telemetry recorder and tuning assistant" \
      org.opencontainers.image.licenses="MIT"

# Unprivileged user. UID/GID 1000 matches the first user on most Linux
# systems; override with `user:` in compose if your data directory differs.
RUN groupadd --gid 1000 pitwall \
    && useradd --uid 1000 --gid 1000 --no-create-home --home-dir /nonexistent \
       --shell /usr/sbin/nologin pitwall \
    && mkdir /data \
    && chown pitwall:pitwall /data

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PITWALL_DATA_DIR=/data \
    PITWALL_WEB_DIR=/app/web

WORKDIR /app

COPY --from=deps /app/.venv /app/.venv
COPY pitwall ./pitwall
COPY web ./web

USER pitwall

VOLUME /data

# 5300/udp: Data Out telemetry from the game. 5301/tcp: web UI and API.
EXPOSE 5300/udp 5301/tcp

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PITWALL_HTTP_PORT', '5301') + '/api/status', timeout=4)"]

CMD ["python", "-m", "pitwall", "serve"]
