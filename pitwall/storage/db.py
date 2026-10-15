"""SQLite storage: sessions, laps, tunes, settings and cached analysis results.

One connection guarded by a lock, so the event loop and the analysis worker
threads can share it. Raw packets live next to the database in ``raw/``
(see :mod:`pitwall.storage.rawlog`).
"""

from __future__ import annotations

import copy
import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pitwall.telemetry.canonical import class_name

SCHEMA_VERSION = 1
DB_NAME = "pitwall.db"
RAW_DIR = "raw"

DEFAULT_SETTINGS: dict[str, Any] = {
    "units": {"speed": "kmh", "temperature": "C", "pressure": "bar"},
    "auto_record": False,
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    stopped_at    TEXT,
    car_ordinal   INTEGER,
    car_pi        INTEGER,
    car_class     INTEGER,
    drivetrain    TEXT,
    track_ordinal INTEGER,
    tune_id       INTEGER REFERENCES tunes(id) ON DELETE SET NULL,
    note          TEXT NOT NULL DEFAULT '',
    raw_file      TEXT,
    frame_count   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS laps (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    number         INTEGER NOT NULL,
    lap_time       REAL,
    kind           TEXT NOT NULL,
    valid          INTEGER NOT NULL,
    invalid_reason TEXT,
    frame_count    INTEGER NOT NULL,
    first_frame    INTEGER NOT NULL,
    started_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS laps_session ON laps(session_id);
CREATE TABLE IF NOT EXISTS tunes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    car_ordinal  INTEGER,
    unit_system  TEXT NOT NULL,
    values_json  TEXT NOT NULL,
    parent_id    INTEGER REFERENCES tunes(id),
    changes_json TEXT NOT NULL DEFAULT '[]',
    note         TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis_cache (
    kind        TEXT NOT NULL,
    ref_id      INTEGER NOT NULL,
    fingerprint TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (kind, ref_id)
);
"""

_LAP_COLUMNS = (
    "id, session_id, number, lap_time, kind, valid, invalid_reason, frame_count, "
    "first_frame, started_at"
)
_SESSION_SELECT = """
SELECT s.*,
       (SELECT COUNT(*) FROM laps l WHERE l.session_id = s.id) AS lap_count,
       (SELECT MIN(l.lap_time) FROM laps l
         WHERE l.session_id = s.id AND l.valid = 1 AND l.kind = 'flying') AS best_lap
FROM sessions s
"""


def iso(epoch: float | None = None) -> str:
    """UTC ISO-8601 with milliseconds, e.g. ``2026-01-31T18:04:05.123Z``."""
    moment = datetime.now(UTC) if epoch is None else datetime.fromtimestamp(epoch, UTC)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class NotFound(LookupError):
    pass


class Store:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.raw_dir = self.data_dir / RAW_DIR
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(
            self.data_dir / DB_NAME, check_same_thread=False, isolation_level=None
        )
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute("PRAGMA synchronous = NORMAL")
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _migrate(self) -> None:
        with self._lock:
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(f"database schema {version} is newer than this pitwall")
            self._db.executescript(_SCHEMA)
            self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _query(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._db.execute(sql, params)

    # --- sessions -----------------------------------------------------------

    def raw_path(self, session: dict[str, Any]) -> Path | None:
        name = session.get("raw_file")
        return self.data_dir / name if name else None

    def create_session(self, *, started_at: str, tune_id: int | None, note: str) -> dict[str, Any]:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO sessions (started_at, tune_id, note) VALUES (?, ?, ?)",
                (started_at, tune_id, note),
            )
            session_id = int(cur.lastrowid or 0)
            raw_file = f"{RAW_DIR}/session-{session_id}.pitwall"
            self._db.execute(
                "UPDATE sessions SET raw_file = ? WHERE id = ?", (raw_file, session_id)
            )
        return self.get_session(session_id)

    def set_session_car(
        self,
        session_id: int,
        *,
        car_ordinal: int,
        car_pi: int,
        car_class: int,
        drivetrain: str | None,
        track_ordinal: int | None,
    ) -> None:
        self._execute(
            "UPDATE sessions SET car_ordinal = ?, car_pi = ?, car_class = ?, drivetrain = ?, "
            "track_ordinal = ? WHERE id = ?",
            (car_ordinal, car_pi, car_class, drivetrain, track_ordinal, session_id),
        )

    def stop_session(self, session_id: int, *, stopped_at: str, frame_count: int) -> None:
        self._execute(
            "UPDATE sessions SET stopped_at = ?, frame_count = ? WHERE id = ?",
            (stopped_at, frame_count, session_id),
        )

    def close_dangling_sessions(self, stopped_at: str) -> int:
        """Sessions left open by a crash: mark them stopped."""
        cur = self._execute(
            "UPDATE sessions SET stopped_at = ? WHERE stopped_at IS NULL", (stopped_at,)
        )
        return cur.rowcount

    def get_session(self, session_id: int) -> dict[str, Any]:
        rows = self._query(_SESSION_SELECT + " WHERE s.id = ?", (session_id,))
        if not rows:
            raise NotFound(f"session {session_id}")
        return _session_dict(rows[0])

    def list_sessions(self) -> list[dict[str, Any]]:
        rows = self._query(_SESSION_SELECT + " ORDER BY s.id DESC")
        return [_session_dict(r) for r in rows]

    def update_session(self, session_id: int, **fields: Any) -> dict[str, Any]:
        allowed = {"note", "tune_id"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        self.get_session(session_id)
        if updates:
            cols = ", ".join(f"{k} = ?" for k in updates)
            self._execute(
                f"UPDATE sessions SET {cols} WHERE id = ?", (*updates.values(), session_id)
            )
        return self.get_session(session_id)

    def delete_session(self, session_id: int) -> None:
        session = self.get_session(session_id)
        with self._lock:
            lap_ids = [
                r["id"]
                for r in self._db.execute("SELECT id FROM laps WHERE session_id = ?", (session_id,))
            ]
            self._db.execute("BEGIN")
            try:
                for lap_id in lap_ids:
                    self._db.execute(
                        "DELETE FROM analysis_cache WHERE kind = 'lap' AND ref_id = ?", (lap_id,)
                    )
                self._db.execute(
                    "DELETE FROM analysis_cache WHERE kind = 'session' AND ref_id = ?",
                    (session_id,),
                )
                self._db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        raw = self.raw_path(session)
        if raw is not None:
            raw.unlink(missing_ok=True)

    def previous_session(self, session: dict[str, Any]) -> dict[str, Any] | None:
        """Most recent earlier session with the same car and track."""
        if session.get("car_ordinal") is None:
            return None
        rows = self._query(
            _SESSION_SELECT + " WHERE s.id < ? AND s.car_ordinal = ? AND s.track_ordinal IS ?"
            " ORDER BY s.id DESC LIMIT 1",
            (session["id"], session["car_ordinal"], session.get("track_ordinal")),
        )
        return _session_dict(rows[0]) if rows else None

    # --- laps ---------------------------------------------------------------

    def insert_lap(
        self,
        *,
        session_id: int,
        number: int,
        lap_time: float | None,
        kind: str,
        valid: bool,
        invalid_reason: str | None,
        frame_count: int,
        first_frame: int,
        started_at: str,
    ) -> dict[str, Any]:
        cur = self._execute(
            "INSERT INTO laps (session_id, number, lap_time, kind, valid, invalid_reason, "
            "frame_count, first_frame, started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                number,
                lap_time,
                kind,
                int(valid),
                invalid_reason,
                frame_count,
                first_frame,
                started_at,
            ),
        )
        return self.get_lap(int(cur.lastrowid or 0))

    def get_lap(self, lap_id: int) -> dict[str, Any]:
        rows = self._query(f"SELECT {_LAP_COLUMNS} FROM laps WHERE id = ?", (lap_id,))
        if not rows:
            raise NotFound(f"lap {lap_id}")
        return _lap_dict(rows[0])

    def list_laps(self, session_id: int) -> list[dict[str, Any]]:
        rows = self._query(
            f"SELECT {_LAP_COLUMNS} FROM laps WHERE session_id = ? ORDER BY id", (session_id,)
        )
        return [_lap_dict(r) for r in rows]

    # --- tunes --------------------------------------------------------------

    def create_tune(
        self,
        *,
        name: str,
        car_ordinal: int | None,
        unit_system: str,
        values: dict[str, float],
        parent_id: int | None,
        changes: list[dict[str, Any]],
        note: str,
    ) -> dict[str, Any]:
        cur = self._execute(
            "INSERT INTO tunes (name, car_ordinal, unit_system, values_json, parent_id, "
            "changes_json, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                car_ordinal,
                unit_system,
                json.dumps(values),
                parent_id,
                json.dumps(changes),
                note,
                iso(),
            ),
        )
        return self.get_tune(int(cur.lastrowid or 0))

    def get_tune(self, tune_id: int) -> dict[str, Any]:
        rows = self._query("SELECT * FROM tunes WHERE id = ?", (tune_id,))
        if not rows:
            raise NotFound(f"tune {tune_id}")
        return _tune_dict(rows[0])

    def list_tunes(self, car_ordinal: int | None = None) -> list[dict[str, Any]]:
        if car_ordinal is None:
            rows = self._query("SELECT * FROM tunes ORDER BY id DESC")
        else:
            rows = self._query(
                "SELECT * FROM tunes WHERE car_ordinal = ? ORDER BY id DESC", (car_ordinal,)
            )
        return [_tune_dict(r) for r in rows]

    # --- key/value state (settings, active tune) ----------------------------

    def get_kv(self, key: str, default: Any = None) -> Any:
        rows = self._query("SELECT value FROM kv WHERE key = ?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set_kv(self, key: str, value: Any) -> None:
        self._execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    def get_settings(self) -> dict[str, Any]:
        stored = self.get_kv("settings", {})
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        settings["units"].update(stored.get("units", {}))
        if "auto_record" in stored:
            settings["auto_record"] = bool(stored["auto_record"])
        return settings

    def save_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        self.set_kv("settings", settings)
        return self.get_settings()

    def get_active_tune_id(self) -> int | None:
        return self.get_kv("active_tune_id")

    def set_active_tune_id(self, tune_id: int | None) -> None:
        self.set_kv("active_tune_id", tune_id)

    # --- analysis cache -----------------------------------------------------

    def get_cached_analysis(self, kind: str, ref_id: int, fingerprint: str) -> Any | None:
        rows = self._query(
            "SELECT fingerprint, result_json FROM analysis_cache WHERE kind = ? AND ref_id = ?",
            (kind, ref_id),
        )
        if not rows or rows[0]["fingerprint"] != fingerprint:
            return None
        return json.loads(rows[0]["result_json"])

    def put_cached_analysis(self, kind: str, ref_id: int, fingerprint: str, result: Any) -> None:
        self._execute(
            "INSERT INTO analysis_cache (kind, ref_id, fingerprint, result_json, created_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(kind, ref_id) DO UPDATE SET "
            "fingerprint = excluded.fingerprint, result_json = excluded.result_json, "
            "created_at = excluded.created_at",
            (kind, ref_id, fingerprint, json.dumps(result), iso()),
        )


def _session_dict(row: sqlite3.Row) -> dict[str, Any]:
    pi = row["car_pi"]
    return {
        "id": row["id"],
        "started_at": row["started_at"],
        "stopped_at": row["stopped_at"],
        "car_ordinal": row["car_ordinal"],
        "car_pi": pi,
        "car_class": row["car_class"],
        "car_class_name": class_name(pi) if pi is not None else None,
        "drivetrain": row["drivetrain"],
        "track_ordinal": row["track_ordinal"],
        "tune_id": row["tune_id"],
        "note": row["note"],
        "lap_count": row["lap_count"],
        "best_lap": row["best_lap"],
        "raw_file": row["raw_file"],
        "frame_count": row["frame_count"],
    }


def _lap_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "number": row["number"],
        "lap_time": row["lap_time"],
        "kind": row["kind"],
        "valid": bool(row["valid"]),
        "invalid_reason": row["invalid_reason"],
        "frame_count": row["frame_count"],
        "first_frame": row["first_frame"],
        "started_at": row["started_at"],
    }


def _tune_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "car_ordinal": row["car_ordinal"],
        "unit_system": row["unit_system"],
        "values": json.loads(row["values_json"]),
        "parent_id": row["parent_id"],
        "changes": json.loads(row["changes_json"]),
        "note": row["note"],
        "created_at": row["created_at"],
    }
