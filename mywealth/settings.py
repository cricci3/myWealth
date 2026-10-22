"""User settings: defaults and validation. Values are stored in the `settings` table."""

from __future__ import annotations

from .db import Database
from .errors import ValidationError

DEFAULTS: dict = {
    "theme": "system",  # system | light | dark
    "offline_mode": False,  # no call to Yahoo Finance at all
    "fx_auto_refresh": True,  # download exchange rates at startup
}

_CHOICES: dict[str, tuple] = {
    "theme": ("system", "light", "dark"),
}

# key -> (min, max) for integer settings
_RANGES: dict[str, tuple[int, int]] = {}


class SettingsError(ValidationError):
    pass


def load(db: Database) -> dict:
    stored = db.get_settings()
    return {k: stored.get(k, default) for k, default in DEFAULTS.items()}


def get(db: Database, key: str):
    return load(db)[key]


def _check(key: str, value):
    default = DEFAULTS[key]
    if key in _CHOICES:
        if value not in _CHOICES[key]:
            raise SettingsError(f"Valore non valido per '{key}'.")
        return value
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise SettingsError(f"Valore non valido per '{key}'.")
        return value
    if isinstance(default, int):
        if isinstance(value, bool) or not isinstance(value, int):
            try:
                value = int(str(value))
            except ValueError:
                raise SettingsError(f"Valore non valido per '{key}'.") from None
        lo, hi = _RANGES.get(key, (None, None))
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            raise SettingsError(f"'{key}' deve essere tra {lo} e {hi}.")
        return value
    if isinstance(default, str):
        if not isinstance(value, str) or len(value) > 200:
            raise SettingsError(f"Valore non valido per '{key}'.")
        return value
    return value


def update(db: Database, changes: dict) -> dict:
    """Validate and save `changes`; unknown keys or invalid values are rejected as a whole."""
    clean = {}
    for key, value in changes.items():
        if key not in DEFAULTS:
            raise SettingsError(f"Impostazione sconosciuta: '{key}'.")
        clean[key] = _check(key, value)
    if clean:
        db.set_settings(clean)
    return load(db)
