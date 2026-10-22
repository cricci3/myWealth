"""Synthetic data for --demo mode. Dates are relative to today, so the demo always looks current."""

from __future__ import annotations

from datetime import date, timedelta

from . import accounts
from .db import Database


def _type_ids(db: Database) -> dict[str, int]:
    return {t["behavior"]: t["id"] for t in accounts.list_types(db) if t["builtin"]}


def seed(db: Database, today: date | None = None) -> None:
    today = today or date.today()
    start = today.replace(day=1) - timedelta(days=365)
    types = _type_ids(db)

    def acc(name, bank, currency, opening, behavior, opened=start):
        return accounts.create_account(db, {
            "name": name, "bank": bank, "currency": currency, "opened_on": opened.isoformat(),
            "opening_balance": opening, "type_id": types[behavior],
        })["id"]

    acc("Conto corrente", "Banca Demo", "EUR", "3200", "standard")
    acc("Conto svizzero", "Banca Alpina", "CHF", "1500", "standard")
    acc("Conto USD", "Bank of Demo", "USD", "800", "standard")
    acc("Salvadanaio", "Banca Demo", "EUR", "5000", "savings")
    acc("Broker", "Broker Demo", "EUR", "2000", "investment")
    acc("Broker USA", "Demo Securities", "USD", "1000", "investment")
