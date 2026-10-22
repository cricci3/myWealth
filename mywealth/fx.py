"""Exchange rates towards EUR."""

from __future__ import annotations

import sqlite3

from .money import BASE


def snapshot(conn: sqlite3.Connection, currency: str, day: str) -> tuple[str | None, str | None]:
    """(rate, rate date) of `currency` -> EUR to store on an operation dated `day`."""
    if currency == BASE:
        return "1", day
    return None, None
