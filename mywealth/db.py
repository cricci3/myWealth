"""SQLite storage with versioned schema migrations.

Each migration is applied in its own transaction and recorded in `schema_version`, so a
crash halfway never leaves a half-migrated database. A database written by a newer app
version is refused instead of being silently downgraded.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

# (version, SQL). Append only: never edit a migration that has been released.
MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL  -- JSON-encoded
        );
        """,
    ),
]

LATEST_VERSION = MIGRATIONS[-1][0]


class SchemaTooNewError(RuntimeError):
    """The database was created by a newer version of the app."""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """A short-lived connection in autocommit mode; use `transaction()` for writes."""
        conn = sqlite3.connect(self.path, isolation_level=None, timeout=10)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    # ---------------------------------------------------------------- schema

    def schema_version(self) -> int:
        with self.connect() as conn:
            return _current_version(conn)

    def migrate(self) -> int:
        """Bring the schema up to date. Returns the number of migrations applied."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version ("
                " version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            current = _current_version(conn)
            if current > LATEST_VERSION:
                raise SchemaTooNewError(
                    f"Database schema v{current} is newer than this app (v{LATEST_VERSION}): "
                    "update myWealth first."
                )
            applied = 0
            for version, sql in MIGRATIONS:
                if version <= current:
                    continue
                now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                # executescript() can't take parameters; both values are trusted constants.
                script = (
                    f"BEGIN IMMEDIATE;\n{sql}\n"
                    f"INSERT INTO schema_version (version, applied_at) VALUES ({int(version)}, '{now}');\n"
                    "COMMIT;"
                )
                try:
                    conn.executescript(script)
                except BaseException:
                    if conn.in_transaction:
                        conn.execute("ROLLBACK")
                    raise
                applied += 1
            return applied

    # -------------------------------------------------------------- settings

    def get_settings(self) -> dict:
        with self.connect() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: json.loads(r["value"]) for r in rows}

    def set_settings(self, values: dict) -> None:
        with self.transaction() as conn:
            conn.executemany(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                [(k, json.dumps(v)) for k, v in values.items()],
            )


def _current_version(conn: sqlite3.Connection) -> int:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
    ).fetchone()
    if not exists:
        return 0
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] or 0
