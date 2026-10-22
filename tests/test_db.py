from __future__ import annotations

import sqlite3

import pytest

from mywealth import db as dbmod
from mywealth import settings
from mywealth.db import LATEST_VERSION, Database, SchemaTooNewError


def test_migrate_fresh_database(tmp_path):
    database = Database(tmp_path / "sub" / "m.db")
    assert database.migrate() == len(dbmod.MIGRATIONS)
    assert database.schema_version() == LATEST_VERSION
    with database.connect() as conn:
        versions = [r[0] for r in conn.execute("SELECT version FROM schema_version ORDER BY version")]
    assert versions == [v for v, _ in dbmod.MIGRATIONS]


def test_migrate_is_idempotent(db):
    assert db.migrate() == 0
    assert db.schema_version() == LATEST_VERSION


def test_pending_migrations_are_applied_in_order(tmp_path, monkeypatch):
    database = Database(tmp_path / "m.db")
    database.migrate()
    extra = [
        (LATEST_VERSION + 1, "CREATE TABLE a (id INTEGER PRIMARY KEY);"),
        (LATEST_VERSION + 2, "ALTER TABLE a ADD COLUMN name TEXT;"),
    ]
    monkeypatch.setattr(dbmod, "MIGRATIONS", dbmod.MIGRATIONS + extra)
    monkeypatch.setattr(dbmod, "LATEST_VERSION", LATEST_VERSION + 2)
    assert database.migrate() == 2
    assert database.schema_version() == LATEST_VERSION + 2
    with database.connect() as conn:
        conn.execute("INSERT INTO a (name) VALUES ('x')")


def test_failed_migration_rolls_back(tmp_path, monkeypatch):
    database = Database(tmp_path / "m.db")
    database.migrate()
    broken = (LATEST_VERSION + 1, "CREATE TABLE b (id INTEGER); THIS IS NOT SQL;")
    monkeypatch.setattr(dbmod, "MIGRATIONS", dbmod.MIGRATIONS + [broken])
    monkeypatch.setattr(dbmod, "LATEST_VERSION", LATEST_VERSION + 1)
    with pytest.raises(sqlite3.Error):
        database.migrate()
    assert database.schema_version() == LATEST_VERSION
    with database.connect() as conn:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'b'").fetchone() is None


def test_newer_schema_is_refused(db):
    with db.connect() as conn:
        conn.execute("INSERT INTO schema_version VALUES (?, 'x')", (LATEST_VERSION + 1,))
    with pytest.raises(SchemaTooNewError):
        db.migrate()


def test_transaction_rolls_back_on_error(db):
    with pytest.raises(RuntimeError):
        with db.transaction() as conn:
            conn.execute("INSERT INTO settings VALUES ('k', '1')")
            raise RuntimeError
    assert db.get_settings() == {}


def test_settings_defaults_and_update(db):
    assert settings.load(db) == settings.DEFAULTS
    assert settings.update(db, {"theme": "dark"})["theme"] == "dark"
    assert settings.load(db)["theme"] == "dark"


@pytest.mark.parametrize("changes", [{"theme": "blue"}, {"unknown": 1}, {"theme": "dark", "unknown": 1}])
def test_settings_rejects_invalid(db, changes):
    with pytest.raises(settings.SettingsError):
        settings.update(db, changes)
    assert settings.load(db) == settings.DEFAULTS
