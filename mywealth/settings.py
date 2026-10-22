"""User settings: defaults and validation. Values are stored in the `settings` table."""

from __future__ import annotations

from pathlib import Path

from .db import Database
from .errors import ValidationError

DEFAULTS: dict = {
    "theme": "system",  # system | light | dark
    "offline_mode": False,  # no call to Yahoo Finance at all
    "fx_auto_refresh": True,  # download exchange rates at startup
    "interest_tax_enabled": False,  # withholding tax on savings interest
    "interest_tax_rate": "26",  # percent, decimal text
    "home_range": "90",  # default range of the Home chart
    "number_format": "it-IT",  # it-IT 1.234,56 | en-GB 1,234.56 (display only)
    "backup_keep": 10,  # automatic backups kept in <data dir>/backups
    "onboarded": False,  # first-run screen already answered
    "app_browser": "auto",  # app window: auto (Brave, then Edge) | brave | edge | default (browser tab)
    "idle_minutes": 5,  # stop the server when no window has been open for this long (0 = never)
    "port": 8777,  # local port (the next free one is used if busy)
    "mobile_inbox_enabled": True,  # look for files from the smartphone in the inbox folder
    "mobile_inbox_dir": "",  # inbox folder; empty = the user's Downloads
}

# Settings tied to this computer: never taken from an imported archive.
MACHINE_KEYS = ("port", "app_browser", "launch_mode", "idle_minutes", "autostart", "mobile_inbox_enabled",
                "mobile_inbox_dir")

_CHOICES: dict[str, tuple] = {
    "theme": ("system", "light", "dark"),
    "home_range": ("30", "60", "90", "max"),
    "app_browser": ("auto", "brave", "edge", "default"),
    "number_format": ("it-IT", "en-GB"),
}

# key -> (min, max) for integer settings
_RANGES: dict[str, tuple[int, int]] = {"backup_keep": (1, 100), "idle_minutes": (0, 1440), "port": (1024, 65535)}


class SettingsError(ValidationError):
    pass


def load(db: Database) -> dict:
    stored = db.get_settings()
    if "app_browser" not in stored and stored.get("launch_mode") == "browser":
        stored["app_browser"] = "default"  # setting of earlier versions: app window or browser tab
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
    if key == "mobile_inbox_dir":
        if not isinstance(value, str) or len(value) > 1000 or "\0" in value:
            raise SettingsError("Cartella non valida.")
        value = value.strip()
        if value and not Path(value).expanduser().is_absolute():
            raise SettingsError("Indica il percorso completo della cartella.")
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
