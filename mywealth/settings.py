"""User settings: defaults and validation. Values are stored in the `settings` table."""

from __future__ import annotations

from .db import Database
from .errors import ValidationError

DEFAULTS: dict = {
    "theme": "system",  # system | light | dark
    "offline_mode": False,  # no call to Yahoo Finance at all
    "fx_auto_refresh": True,  # download exchange rates at startup
    "interest_tax_enabled": False,  # withholding tax on savings interest
    "interest_tax_rate": "26",  # percent, decimal text
    "home_range": "90",  # default range of the Home chart
    "backup_keep": 10,  # automatic backups kept in <data dir>/backups
    "onboarded": False,  # first-run screen already answered
}

# Settings tied to this computer: never taken from an imported archive.
MACHINE_KEYS = ("port", "launch_mode", "idle_minutes", "autostart")

_CHOICES: dict[str, tuple] = {
    "theme": ("system", "light", "dark"),
    "home_range": ("30", "60", "90", "max"),
}

# key -> (min, max) for integer settings
_RANGES: dict[str, tuple[int, int]] = {"backup_keep": (1, 100)}


class SettingsError(ValidationError):
    pass


def load(db: Database) -> dict:
    stored = db.get_settings()
    return {k: stored.get(k, default) for k, default in DEFAULTS.items()}


def get(db: Database, key: str):
    return load(db)[key]


def _check(key: str, value):
    default = DEFAULTS[key]
    if key == "interest_tax_rate":
        from .money import parse_decimal

        rate = parse_decimal(value, "ritenuta", max_places=2)
        if rate < 0 or rate > 100:
            raise SettingsError("La ritenuta deve essere tra 0 e 100%.")
        return format(rate.normalize(), "f")
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
