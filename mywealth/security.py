"""Optional unlock PIN for the app.

The PIN locks the interface and the API of the running app (e.g. a shared PC with the
window left open); it does NOT encrypt the data on disk — that is BitLocker's job.
Stored as PBKDF2-SHA256 with a random salt; repeated wrong attempts are slowed down.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time

from .db import Database
from .errors import AppError, ValidationError

KEY = "pin"
ITERATIONS = 200_000
MAX_FAILURES = 5
BLOCK_SECONDS = 30
_PIN_RE = re.compile(r"^\d{4,12}$")


class LockedError(AppError):
    status = 423


def _hash(pin: str, salt: bytes, iterations: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, iterations).hex()


def is_set(db: Database) -> bool:
    return bool(db.get_settings().get(KEY))


def verify(db: Database, pin: str) -> bool:
    data = db.get_settings().get(KEY)
    if not data:
        return True
    expected = data["hash"]
    got = _hash(str(pin or ""), bytes.fromhex(data["salt"]), int(data["iterations"]))
    return hmac.compare_digest(expected, got)


def set_pin(db: Database, new_pin: str, current: str | None) -> None:
    """Set, change (current PIN required) or remove (empty new PIN) the PIN."""
    if is_set(db) and not verify(db, current or ""):
        raise ValidationError("PIN attuale errato.")
    if not new_pin:
        db.set_settings({KEY: None})
        return
    if not _PIN_RE.match(str(new_pin)):
        raise ValidationError("Il PIN deve avere da 4 a 12 cifre.")
    salt = secrets.token_bytes(16)
    db.set_settings({KEY: {"salt": salt.hex(), "iterations": ITERATIONS, "hash": _hash(str(new_pin), salt, ITERATIONS)}})


class Gate:
    """Lock state of one running app (kept in memory: every start begins locked)."""

    def __init__(self) -> None:
        self.unlocked = False
        self.failures = 0
        self.blocked_until = 0.0

    def locked(self, db: Database) -> bool:
        return not self.unlocked and is_set(db)

    def unlock(self, db: Database, pin: str) -> None:
        now = time.monotonic()
        if now < self.blocked_until:
            raise LockedError(f"Troppi tentativi: riprova tra {int(self.blocked_until - now) + 1} secondi.")
        if verify(db, pin):
            self.unlocked = True
            self.failures = 0
            return
        self.failures += 1
        if self.failures >= MAX_FAILURES:
            self.failures = 0
            self.blocked_until = now + BLOCK_SECONDS
            raise LockedError(f"PIN errato. Troppi tentativi: attendi {BLOCK_SECONDS} secondi.")
        raise LockedError("PIN errato.")

    def lock(self) -> None:
        self.unlocked = False
