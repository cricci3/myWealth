"""Smartphone entry (SPEC §16), desktop side: pairing key, configuration QR and the inbox
folder where the encrypted files sent from the phone arrive.

The files are AES-256-GCM encrypted by the PWA. Python has no AES in the standard library
and compiled dependencies may be blocked by AppLocker/WDAC, so they are decrypted in the
page with the Web Crypto API: the server only finds them, hands the page their text and the
key (on 127.0.0.1, behind the token) and deletes them after a successful import.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import secrets
import sys
from pathlib import Path

from . import accounts, categories, money
from .db import Database, now_iso
from .errors import NotFoundError, ValidationError

log = logging.getLogger(__name__)

KEY_FILENAME = "mobile_key.json"
FILE_MAGIC = "MYWEALTH-ENC 1"
FILE_PREFIX = "mywealth-"
MAX_FILE_BYTES = 2 * 1024 * 1024
PAIR_VERSION = 1
QR_CHUNK = 700  # characters per QR code: above this the configuration is split in a sequence
QR_CHUNK_PREFIX = "MWQR"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def key_id(key: bytes) -> str:
    """`kid`: first 8 bytes of the SHA-256 of the key, in hex. Identifies the key, reveals nothing."""
    return hashlib.sha256(key).hexdigest()[:16]


# --------------------------------------------------------------------- key --


def _key_path(data_dir: Path) -> Path:
    return Path(data_dir) / KEY_FILENAME


def load_key(data_dir: Path) -> dict | None:
    """{"key": base64url, "kid", "created"} or None when no phone is paired."""
    path = _key_path(data_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = base64.urlsafe_b64decode(data["key"] + "=" * (-len(data["key"]) % 4))
        if len(raw) != 32 or data.get("kid") != key_id(raw):
            raise ValueError("inconsistent key file")
    except (OSError, ValueError, KeyError, TypeError):
        log.warning("Unreadable %s: the phone must be paired again", KEY_FILENAME)
        return None
    return {"key": data["key"], "kid": data["kid"], "created": data.get("created")}


def create_key(data_dir: Path) -> dict:
    """New random 256-bit key (replaces the previous one: its files can't be read any more)."""
    raw = secrets.token_bytes(32)
    data = {"v": PAIR_VERSION, "key": b64url(raw), "kid": key_id(raw), "created": now_iso()}
    path = _key_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)
    return {k: data[k] for k in ("key", "kid", "created")}


def status(data_dir: Path) -> dict:
    key = load_key(data_dir)
    return {"paired": key is not None, "kid": key and key["kid"], "created": key and key["created"]}


# ------------------------------------------------------- configuration QR --


def configuration(db: Database) -> dict:
    """What the phone needs to fill its menus: active accounts [name, currency, decimals] and
    categories by nature."""
    accs = [[a["name"], a["currency"], money.decimals(a["currency"])]
            for a in accounts.list_accounts(db, include_archived=False)]
    cats: dict[str, list[str]] = {n: [] for n in categories.NATURES}
    for c in categories.list_categories(db):
        if not c["archived"]:
            cats[c["nature"]].append(c["name"])
    return {"accounts": accs, "categories": cats}


def pairing_payload(db: Database, key: dict) -> str:
    """Compact JSON read by the PWA: version, key, kid, date and configuration."""
    data = {"mw": PAIR_VERSION, "key": key["key"], "kid": key["kid"], "at": now_iso(), **configuration(db)}
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def split_payload(text: str, size: int = QR_CHUNK) -> list[str]:
    """One QR when it fits, otherwise `MWQR:<i>/<n>:<part>` codes scanned in sequence."""
    if len(text) <= size:
        return [text]
    parts = [text[i:i + size] for i in range(0, len(text), size)]
    return [f"{QR_CHUNK_PREFIX}:{i}/{len(parts)}:{p}" for i, p in enumerate(parts, start=1)]


def qr_svg(text: str) -> str:
    import segno  # pure Python: no compiled extension for AppLocker/WDAC to block

    qr = segno.make(text, error="m", micro=False)
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=1, border=4, dark="#000", light="#fff", xmldecl=False, svgclass="qr",
            lineclass=None, omitsize=True, nl=False)
    return buf.getvalue().decode("utf-8")


def pairing(db: Database, data_dir: Path, regenerate: bool = False) -> dict:
    """Key (created on the first pairing or on request) and the QR codes that carry it."""
    key = None if regenerate else load_key(data_dir)
    if key is None:
        key = create_key(data_dir)
        log.info("New smartphone key created (kid %s)", key["kid"])
    text = pairing_payload(db, key)
    parts = split_payload(text)
    return {"kid": key["kid"], "created": key["created"], "text": text, "qr": [qr_svg(p) for p in parts]}


# ------------------------------------------------------------------ inbox --


def downloads_dir() -> Path:
    """The user's Downloads folder (wherever Windows has moved it)."""
    if sys.platform.startswith("win"):
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as k:
                value, _ = winreg.QueryValueEx(k, "{374DE290-123F-4565-9164-39C4925E467B}")
                if value:
                    return Path(os.path.expandvars(value))
        except OSError:
            pass
    return Path.home() / "Downloads"


def inbox_dir(prefs: dict, data_dir: Path, demo: bool = False) -> Path | None:
    """Folder searched for files from the phone, or None when the inbox is off. The demo
    never looks at the real Downloads folder: it uses a folder inside its temporary data."""
    if not prefs.get("mobile_inbox_enabled"):
        return None
    custom = (prefs.get("mobile_inbox_dir") or "").strip()
    if custom:
        return Path(custom).expanduser()
    return Path(data_dir) / "inbox" if demo else downloads_dir()


def is_candidate_name(name: str) -> bool:
    low = name.lower()
    return (low.startswith(FILE_PREFIX) and low.endswith(".txt") and len(name) <= 120
            and "/" not in name and "\\" not in name and name not in (".", ".."))


def _has_magic(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(len(FILE_MAGIC) + 3)
    except OSError:
        return False
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    return head.startswith(FILE_MAGIC.encode("ascii"))


def scan_inbox(folder: Path | None) -> list[dict]:
    """Encrypted files from the phone in the folder: only `mywealth-*.txt` names are looked
    at, and of those only the first bytes are read. Other files are never opened."""
    if folder is None or not folder.is_dir():
        return []
    found = []
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return []
    for e in entries:
        if not is_candidate_name(e.name):
            continue
        try:
            if not e.is_file() or e.stat().st_size > MAX_FILE_BYTES:
                continue
            st = e.stat()
        except OSError:
            continue
        if _has_magic(Path(e.path)):
            found.append({"name": e.name, "size": st.st_size, "modified": st.st_mtime})
    found.sort(key=lambda f: f["modified"])
    return found


def _inbox_file(folder: Path | None, name: str) -> Path:
    if folder is None:
        raise ValidationError("La cartella in arrivo è disattivata.")
    if not is_candidate_name(name):
        raise ValidationError("Nome di file non valido.")
    path = folder / name
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES or not _has_magic(path):
        raise NotFoundError(f"File '{name}' non trovato nella cartella in arrivo.")
    return path


def read_inbox_file(folder: Path | None, name: str) -> str:
    return _inbox_file(folder, name).read_text(encoding="utf-8-sig")


def delete_inbox_files(folder: Path | None, names: list[str]) -> list[str]:
    """Remove imported files; a file that can't be removed is only logged."""
    deleted = []
    for name in names:
        try:
            _inbox_file(folder, name).unlink()
            deleted.append(name)
        except (OSError, ValidationError, NotFoundError) as e:
            log.warning("Could not delete %s from the inbox: %s", name, e)
    return deleted
