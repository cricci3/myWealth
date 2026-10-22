"""Synthetic data for --demo mode. Dates are relative to today, so the demo always looks current."""

from __future__ import annotations

import random
from datetime import date, timedelta

from . import accounts, categories, transactions
from .db import Database


def _type_ids(db: Database) -> dict[str, int]:
    return {t["behavior"]: t["id"] for t in accounts.list_types(db) if t["builtin"]}


def _months(start: date, today: date):
    d = start
    while d <= today:
        yield d
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def seed(db: Database, today: date | None = None) -> None:
    today = today or date.today()
    start = today.replace(day=1) - timedelta(days=365)
    start = start.replace(day=1)
    types = _type_ids(db)
    rng = random.Random(7)

    def acc(name, bank, currency, opening, behavior):
        return accounts.create_account(db, {
            "name": name, "bank": bank, "currency": currency, "opened_on": start.isoformat(),
            "opening_balance": opening, "type_id": types[behavior],
        })["id"]

    main = acc("Conto corrente", "Banca Demo", "EUR", "3200", "standard")
    chf = acc("Conto svizzero", "Banca Alpina", "CHF", "1500", "standard")
    usd = acc("Conto USD", "Bank of Demo", "USD", "1200", "standard")
    savings = acc("Salvadanaio", "Banca Demo", "EUR", "5000", "savings")
    broker = acc("Broker", "Broker Demo", "EUR", "2000", "investment")
    broker_us = acc("Broker USA", "Demo Securities", "USD", "1000", "investment")

    cats = {(c["name"], c["nature"]): c["id"] for c in categories.list_categories(db)}

    def cat(name, nature="expense"):
        return cats[(name, nature)]

    def add(kind, day: date, **data):
        if day > today:
            return
        transactions.create(db, {"kind": kind, "date": day.isoformat(), **data})

    def money_str(value: float) -> str:
        return f"{value:.2f}"

    for m in _months(start, today):
        def day(n):
            return m.replace(day=min(n, 28))

        add("income", day(27), account_id=main, amount="2450", category_id=cat("Stipendio", "income"),
            description="Stipendio")
        add("expense", day(1), account_id=main, amount="850", category_id=cat("Affitto"), description="Affitto")
        add("expense", day(6), account_id=main, amount=money_str(rng.uniform(60, 140)), category_id=cat("Bollette"),
            description="Luce e gas")
        add("expense", day(12), account_id=main, amount="29.99", category_id=cat("Bollette"), description="Internet")
        add("expense", day(3), account_id=main, amount="12.99", category_id=cat("Abbonamenti"), description="Musica")
        add("expense", day(15), account_id=usd, amount="15.49", category_id=cat("Abbonamenti"),
            description="Servizio streaming")
        for week in (2, 9, 16, 23):
            add("expense", day(week), account_id=main, amount=money_str(rng.uniform(45, 95)),
                category_id=cat("Spesa alimentare"), description="Supermercato")
        for _ in range(rng.randint(2, 4)):
            add("expense", day(rng.randint(1, 28)), account_id=main, amount=money_str(rng.uniform(18, 70)),
                category_id=cat("Ristoranti"), description=rng.choice(["Pizzeria", "Trattoria", "Sushi", "Aperitivo"]))
        add("expense", day(rng.randint(1, 28)), account_id=main, amount=money_str(rng.uniform(30, 60)),
            category_id=cat("Trasporti"), description="Carburante")
        if rng.random() < 0.5:
            add("expense", day(rng.randint(1, 28)), account_id=main, amount=money_str(rng.uniform(20, 90)),
                category_id=cat("Salute"), description="Farmacia")
        if rng.random() < 0.6:
            add("expense", day(rng.randint(1, 28)), account_id=main, amount=money_str(rng.uniform(25, 120)),
                category_id=cat("Svago"), description=rng.choice(["Cinema", "Concerto", "Libri", "Sport"]))
        add("expense", day(rng.randint(1, 28)), account_id=chf, amount=money_str(rng.uniform(40, 160)),
            category_id=cat("Spesa alimentare"), description="Coop")
        add("transfer", day(28), from_account_id=main, to_account_id=savings, amount="300",
            description="Risparmio mensile")
        add("transfer", day(5), from_account_id=main, to_account_id=broker, amount="400",
            description="Piano di accumulo")
        if m.month % 3 == 0:
            sent = rng.uniform(300, 400)
            add("transfer", day(10), from_account_id=main, to_account_id=chf, sent_amount=money_str(sent),
                amount=money_str(sent * 0.94), fee_amount="2.50", fee_side="from", description="Cambio in CHF")
        if m.month in (6, 12):
            add("expense", day(18), account_id=main, amount=money_str(rng.uniform(400, 900)),
                category_id=cat("Viaggi"), description="Vacanza")
        if m.month == 4:
            add("expense", day(20), account_id=main, amount="320", category_id=cat("Tasse"), description="Tasse")
        if m.month == 7:
            add("income", day(20), account_id=main, amount="180", category_id=cat("Rimborsi", "income"),
                description="Rimborso spese")
        if m.month % 4 == 1:
            add("transfer", day(8), from_account_id=usd, to_account_id=broker_us, amount="200",
                description="Versamento broker USA")
