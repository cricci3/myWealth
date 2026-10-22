from __future__ import annotations

import io
import json
import zipfile

import pytest

from mywealth import accounts, archive, db as dbmod, settings
from mywealth.db import Database
from mywealth.errors import NotFoundError, ValidationError

from .helpers import make_account


def test_build_and_inspect(db, isolated_data_dir):
    make_account(db, "Corrente", "EUR", "10")
    data = archive.build(db)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert set(z.namelist()) == {"manifest.json", "settings.json", "mywealth.db"}
    manifest, raw = archive.inspect(data)
    assert manifest["accounts"] == 1 and manifest["schema_version"] == dbmod.LATEST_VERSION
    assert raw.startswith(b"SQLite format 3")
    assert archive.filename().endswith(".mywealth")


def _tamper(data: bytes, **changes) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name in src.namelist():
            content = src.read(name)
            if name == "manifest.json":
                m = json.loads(content)
                m.update(changes.get("manifest", {}))
                content = json.dumps(m).encode()
            if name == "mywealth.db" and "db" in changes:
                content = changes["db"]
            if name not in changes.get("drop", ()):
                z.writestr(name, content)
    return out.getvalue()


def test_invalid_archives(db):
    data = archive.build(db)
    with pytest.raises(ValidationError, match="valido"):
        archive.inspect(b"not a zip")
    with pytest.raises(ValidationError, match="Checksum"):
        archive.inspect(_tamper(data, db=b"SQLite format 3\x00garbage"))
    with pytest.raises(ValidationError, match="recente"):
        archive.inspect(_tamper(data, manifest={"schema_version": dbmod.LATEST_VERSION + 1, "app_version": "9.9"}))
    with pytest.raises(ValidationError, match="incompleto"):
        archive.inspect(_tamper(data, drop=("mywealth.db",)))


def test_restore_replaces_data_and_keeps_machine_settings(db, isolated_data_dir, tmp_path):
    other = Database(tmp_path / "other.db")
    other.migrate()
    make_account(other, "Dal vecchio PC", "EUR", "123")
    settings.update(other, {"theme": "dark"})
    other.set_settings({"port": 1111})
    exported = archive.build(other)

    make_account(db, "Attuale", "EUR", "1")
    db.set_settings({"port": 2222})
    out = archive.restore(db, isolated_data_dir, exported)
    assert out["restored"]["accounts"] == 1
    assert [a["name"] for a in accounts.list_accounts(db)] == ["Dal vecchio PC"]
    assert settings.get(db, "theme") == "dark"
    assert db.get_settings()["port"] == 2222  # machine setting kept
    # the previous data was backed up and can be restored
    backups = archive.list_backups(isolated_data_dir)
    assert backups and "pre-import" in backups[0]["name"]
    archive.restore_backup(db, isolated_data_dir, out["backup"])
    assert "Attuale" in [a["name"] for a in accounts.list_accounts(db)]


def test_restore_from_older_schema_migrates(db, isolated_data_dir, tmp_path, monkeypatch):
    old = Database(tmp_path / "old.db")
    monkeypatch.setattr(dbmod, "MIGRATIONS", dbmod.MIGRATIONS[:2])
    monkeypatch.setattr(dbmod, "LATEST_VERSION", 2)
    old.migrate()
    make_account(old, "Vecchio", "EUR", "5")
    data = archive.build(old)
    monkeypatch.undo()
    archive.restore(db, isolated_data_dir, data)
    assert db.schema_version() == dbmod.LATEST_VERSION
    assert accounts.list_accounts(db)[0]["name"] == "Vecchio"


def test_backups_rotation_and_names(db, isolated_data_dir):
    for _ in range(4):
        archive.create_backup(db, isolated_data_dir, "auto", keep=3)
    assert len(archive.list_backups(isolated_data_dir)) == 3
    with pytest.raises(ValidationError):
        archive.backup_path(isolated_data_dir, "../mywealth.db")
    with pytest.raises(NotFoundError):
        archive.backup_path(isolated_data_dir, "missing.mywealth")


def test_is_empty(db):
    assert archive.is_empty(db)
    make_account(db, "X", "EUR", "0")
    assert not archive.is_empty(db)


def test_archive_api(server, db, isolated_data_dir):
    _, client = server
    make_account(db, "Corrente", "EUR", "10")
    status, headers, data = client.request("GET", "/api/archive")
    assert status == 200 and headers["Content-Disposition"].count(".mywealth")
    status, res = client.json("POST", "/api/archive/inspect", data)
    assert status == 200 and res["archive"]["accounts"] == 1 and res["current_empty"] is False
    assert client.json("POST", "/api/archive/inspect", b"junk")[0] == 400
    status, res = client.json("POST", "/api/archive/restore", data)
    assert status == 200 and res["backup"]
    status, res = client.json("GET", "/api/backups")
    assert res["items"]
    name = res["items"][0]["name"]
    assert client.request("GET", f"/api/backups/{name}")[0] == 200
    assert client.json("POST", "/api/backups")[0] == 200
    assert client.json("POST", f"/api/backups/{name}/restore")[0] == 200
    assert client.json("GET", "/api/onboarding")[1] == {"show": False}  # demo context


def test_startup_backup_and_onboarding(db, isolated_data_dir):
    from mywealth import api, app
    from mywealth.router import Request
    from mywealth.server import AppContext

    ctx = AppContext(db=db, data_dir=isolated_data_dir)
    settings.update(db, {"fx_auto_refresh": False})
    req = Request("GET", {}, {}, dict)
    assert api.onboarding(ctx, req) == {"show": True}
    app.startup(ctx)
    assert archive.list_backups(isolated_data_dir) == []  # nothing to back up yet
    make_account(db, "Corrente", "EUR", "1")
    assert api.onboarding(ctx, req) == {"show": False}
    app.startup(ctx)
    assert len(archive.list_backups(isolated_data_dir)) == 1
