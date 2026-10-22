"""User settings: defaults and validation. Values are stored in the `settings` table."""

from __future__ import annotations

from .db import Database
from .errors import ValidationError

DEFAULTS: dict = {
    "theme": "system",  # system | light | dark
}

_CHOICES: dict[str, tuple] = {
    "theme": ("system", "light", "dark"),
}


class SettingsError(ValidationError):
    pass


def load(db: Database) -> dict:
    stored = db.get_settings()
    return {k: stored.get(k, default) for k, default in DEFAULTS.items()}


def update(db: Database, changes: dict) -> dict:
    """Validate and save `changes`; unknown keys or invalid values are rejected as a whole."""
    clean = {}
    for key, value in changes.items():
        if key not in DEFAULTS:
            raise SettingsError(f"Impostazione sconosciuta: '{key}'.")
        if key in _CHOICES and value not in _CHOICES[key]:
            raise SettingsError(f"Valore non valido per '{key}'.")
        clean[key] = value
    if clean:
        db.set_settings(clean)
    return load(db)
