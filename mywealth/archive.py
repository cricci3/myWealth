"""`.mywealth` archives: "Esporta tutto" / "Importa tutto" and automatic backups.

An archive is a ZIP file with:
  - mywealth.db    consistent copy of the database (SQLite backup API, never a raw copy)
  - settings.json  the app settings
  - manifest.json  app and schema version, creation time, counts, SHA-256 of the database

Importing replaces all the data (no merge). The current data is backed up first, and
settings tied to this computer (port, shortcuts, startup) are kept.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from . import __version__, settings
from .db import LATEST_VERSION, Database, now_iso
from .errors import NotFoundError, ValidationError

log = logging.getLogger(__name__)

BACKUPS_DIRNAME = "backups"
EXTENSION = ".mywealth"
FORMAT = 1
MAX_DB_SIZE = 2_000_000_000
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+\.mywealth$")


def _snapshot(db: Database, dest: Path) -> None:
    """Consistent copy of the live database through the SQLite backup API."""
    src = sqlite3.connect(db.path, timeout=30)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _counts(path: Path) -> dict:
    conn = sqlite3.connect(path)
    try:
        def count(table: str) -> int:
            try:
                return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.Error:
                return 0
        return {"accounts": count("accounts"), "transactions": count("transactions"), "assets": count("assets")}
    finally:
        conn.close()


def build(db: Database) -> bytes:
    """The whole data set as a .mywealth archive (bytes)."""
    with tempfile.TemporaryDirectory(prefix="mywealth-export-") as tmp:
        snap = Path(tmp) / "mywealth.db"
        _snapshot(db, snap)
        raw = snap.read_bytes()
        manifest = {
            "format": FORMAT,
            "app_version": __version__,
            "schema_version": db.schema_version(),
            "created_at": now_iso(),
            **_counts(snap),
            "db_sha256": hashlib.sha256(raw).hexdigest(),
        }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        z.writestr("settings.json", json.dumps(settings.load(db), indent=2))
        z.writestr("mywealth.db", raw)
    return buf.getvalue()


def filename(prefix: str = "myWealth") -> str:
    return f"{prefix}_{datetime.now().strftime('%Y-%m-%d')}{EXTENSION}"


def inspect(data: bytes) -> tuple[dict, bytes]:
    """Validate an archive; returns (manifest, database bytes). Raises ValidationError."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValidationError("Il file non è un archivio myWealth valido.") from None
    with z:
        names = set(z.namelist())
        if not {"manifest.json", "mywealth.db"} <= names:
            raise ValidationError("Archivio incompleto: mancano manifest.json o mywealth.db.")
        info = z.getinfo("mywealth.db")
        if info.file_size > MAX_DB_SIZE:
            raise ValidationError("Database nell'archivio troppo grande.")
        try:
            manifest = json.loads(z.read("manifest.json"))
        except ValueError:
            raise ValidationError("manifest.json non valido.") from None
        raw = z.read("mywealth.db")
    if not isinstance(manifest, dict):
        raise ValidationError("manifest.json non valido.")
    if hashlib.sha256(raw).hexdigest() != manifest.get("db_sha256"):
        raise ValidationError("Checksum errato: l'archivio è danneggiato.")
    schema = manifest.get("schema_version")
    if not isinstance(schema, int):
        raise ValidationError("Versione dello schema mancante.")
    if schema > LATEST_VERSION:
        raise ValidationError(
            f"L'archivio è stato creato da una versione più recente di myWealth ({manifest.get('app_version')}): "
            "aggiorna prima l'app."
        )
    return manifest, raw


def summary(manifest: dict) -> dict:
    return {k: manifest.get(k) for k in ("app_version", "schema_version", "created_at", "accounts", "transactions",
                                         "assets")}


def restore(db: Database, data_dir: Path, data: bytes, keep: int | None = None) -> dict:
    """Replace all the data with the archive. The current data is backed up first."""
    manifest, raw = inspect(data)
    with tempfile.TemporaryDirectory(prefix="mywealth-import-", dir=data_dir) as tmp:
        src_path = Path(tmp) / "import.db"
        src_path.write_bytes(raw)
        src = sqlite3.connect(src_path)
        try:
            ok = src.execute("PRAGMA integrity_check").fetchone()[0]
            if ok != "ok":
                raise ValidationError("Il database nell'archivio è danneggiato.")
            real_schema = src.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0
        except sqlite3.DatabaseError:
            raise ValidationError("Il database nell'archivio non è leggibile.") from None
        finally:
            src.close()
        if real_schema > LATEST_VERSION:
            raise ValidationError("L'archivio è stato creato da una versione più recente di myWealth: aggiorna prima l'app.")

        backup = create_backup(db, data_dir, "pre-import", keep)
        machine = {k: v for k, v in db.get_settings().items() if k in settings.MACHINE_KEYS}

        src = sqlite3.connect(src_path)
        dst = sqlite3.connect(db.path, timeout=30)
        try:
            src.backup(dst)  # replaces the live database content atomically, page by page
        finally:
            dst.close()
            src.close()
    db.migrate()  # archives from older versions are brought up to date
    if machine:
        db.set_settings(machine)
    log.info("Data replaced from an archive created on %s", manifest.get("created_at"))
    return {"restored": summary(manifest), "backup": backup}


# --------------------------------------------------------------------- backups


def backups_dir(data_dir: Path) -> Path:
    return Path(data_dir) / BACKUPS_DIRNAME


def create_backup(db: Database, data_dir: Path, reason: str = "auto", keep: int | None = None) -> str:
    """Write a .mywealth archive into <data dir>/backups and prune the oldest ones."""
    folder = backups_dir(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    reason = re.sub(r"[^a-z-]", "", reason)[:20] or "auto"
    name = f"myWealth_{stamp}_{reason}{EXTENSION}"
    path = folder / name
    n = 1
    while path.exists():
        path = folder / f"myWealth_{stamp}_{reason}-{n}{EXTENSION}"
        n += 1
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(build(db))
    os.replace(tmp, path)
    prune(data_dir, keep if keep is not None else settings.get(db, "backup_keep"))
    return path.name


def list_backups(data_dir: Path) -> list[dict]:
    folder = backups_dir(data_dir)
    if not folder.exists():
        return []
    out = []
    for p in folder.glob(f"*{EXTENSION}"):
        st = p.stat()
        out.append({"name": p.name, "size": st.st_size,
                    "created_at": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")})
    return sorted(out, key=lambda b: b["created_at"], reverse=True)


def prune(data_dir: Path, keep: int) -> None:
    for b in list_backups(data_dir)[max(1, int(keep)):]:
        try:
            (backups_dir(data_dir) / b["name"]).unlink()
        except OSError:
            log.warning("Could not delete old backup %s", b["name"])


def backup_path(data_dir: Path, name: str) -> Path:
    if not _NAME_RE.match(name or ""):
        raise ValidationError("Nome del backup non valido.")
    path = backups_dir(data_dir) / name
    if not path.is_file():
        raise NotFoundError("Backup non trovato.")
    return path


def restore_backup(db: Database, data_dir: Path, name: str) -> dict:
    return restore(db, data_dir, backup_path(data_dir, name).read_bytes())


def is_empty(db: Database) -> bool:
    with db.connect() as conn:
        return conn.execute("SELECT (SELECT COUNT(*) FROM accounts) + (SELECT COUNT(*) FROM transactions)").fetchone()[0] == 0
