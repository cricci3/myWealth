"""Home: net worth in EUR, totals per currency, per-account values and history."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from decimal import Decimal

from . import accounts, fx, investments, money
from .db import Database

ZERO = Decimal(0)
RANGES = {"30": 30, "60": 60, "90": 90, "180": 180, "365": 365, "max": None}
MAX_POINTS = 366


def summary(db: Database, today: date | None = None) -> dict:
    """Current value of every account, in its currency and in EUR (latest rate)."""
    today = today or date.today()
    with db.connect() as conn:
        accs = accounts.list_accounts(db)
        positions = investments.market_values(conn, today)
        rates = {cur: fx.latest_rate(conn, cur) for cur in {a["currency"] for a in accs}}
        rate_info = fx.latest(conn)
    cards = []
    total_eur = ZERO
    by_currency: dict[str, Decimal] = {}
    missing: list[str] = []
    for a in accs:
        cur = a["currency"]
        cash = money.from_minor(a["balance_minor"], cur)
        invested_value = positions.get(a["id"], ZERO) if a["behavior"] == "investment" else ZERO
        value = cash + invested_value
        rate = rates.get(cur)
        eur = value * rate if rate is not None else None
        if not a["archived"] or value != 0:
            by_currency[cur] = by_currency.get(cur, ZERO) + value
            if eur is not None:
                total_eur += eur
            elif cur not in missing:
                missing.append(cur)
        if a["archived"]:
            continue
        info = rate_info.get(cur, {})
        cards.append({
            "id": a["id"], "name": a["name"], "bank": a["bank"], "currency": cur, "behavior": a["behavior"],
            "type_name": a["type_name"], "annual_rate": a.get("annual_rate"),
            "cash": money.fmt_decimal(cash, money.decimals(cur)),
            "positions": money.fmt_decimal(invested_value) if a["behavior"] == "investment" else None,
            "value": money.fmt_decimal(value, money.decimals(cur)),
            "eur": money.fmt_decimal(eur) if eur is not None else None,
            "rate": str(rate) if rate is not None and cur != money.BASE else None,
            "rate_date": info.get("date") if cur != money.BASE else None,
        })
    return {
        "date": today.isoformat(),
        "total_eur": money.fmt_decimal(total_eur),
        "by_currency": [{"currency": c, "value": money.fmt_decimal(v, money.decimals(c))}
                        for c, v in sorted(by_currency.items(), key=lambda kv: (kv[0] != money.BASE, kv[0]))],
        "missing_rates": missing,
        "accounts": cards,
    }


def _cash_series(conn: sqlite3.Connection, acc: sqlite3.Row, start: date, end: date) -> dict[date, Decimal]:
    """End-of-day cash balance for every day in [start, end] (0 before the opening)."""
    cur = acc["currency"]
    opened = date.fromisoformat(acc["opened_on"])
    before = accounts.balance(conn, acc["id"], (start - timedelta(days=1)).isoformat()) if opened < start else 0
    moves: dict[str, int] = {}
    for d, amount in conn.execute(
        """SELECT date, SUM(CASE WHEN to_account_id = :a THEN to_amount ELSE 0 END)
                      - SUM(CASE WHEN from_account_id = :a THEN from_amount ELSE 0 END)
           FROM transactions WHERE (from_account_id = :a OR to_account_id = :a) AND date BETWEEN :s AND :e
           GROUP BY date""",
        {"a": acc["id"], "s": start.isoformat(), "e": end.isoformat()},
    ):
        moves[d] = amount
    out: dict[date, Decimal] = {}
    bal = before
    d = start
    while d <= end:
        if d == opened:
            bal = acc["opening_balance"]
        if d >= opened:
            bal += moves.get(d.isoformat(), 0)
            out[d] = money.from_minor(bal, cur)
        else:
            out[d] = ZERO
        d += timedelta(days=1)
    return out


def history(db: Database, range_key: str = "90", today: date | None = None, max_points: int = MAX_POINTS) -> dict:
    """Daily value in EUR of every account and of the total, rebuilt from the operations
    (and, for investment accounts, from the cached historical prices)."""
    today = today or date.today()
    if range_key not in RANGES:
        range_key = "90"
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT a.*, t.behavior FROM accounts a JOIN account_types t ON t.id = a.type_id
               ORDER BY a.archived, a.name COLLATE NOCASE"""
        ).fetchall()
        if not rows:
            return {"range": range_key, "dates": [], "total": [], "accounts": []}
        first_open = min(date.fromisoformat(r["opened_on"]) for r in rows)
        days = RANGES[range_key]
        start = first_open if days is None else max(first_open, today - timedelta(days=days))
        all_days = [start + timedelta(days=i) for i in range((today - start).days + 1)]
        lines = []
        total = [ZERO] * len(all_days)
        complete = [True] * len(all_days)
        for acc in rows:
            cur = acc["currency"]
            cash = _cash_series(conn, acc, start, today)
            pos = investments.value_series(conn, acc["id"], cur, today) if acc["behavior"] == "investment" else {}
            rates = fx.daily_series(conn, cur, start, today)
            values: list[Decimal | None] = []
            last_pos = ZERO
            opened = date.fromisoformat(acc["opened_on"])
            # positions value before the first day of the range
            if pos:
                earlier = [d for d in pos if d < start]
                if earlier:
                    last_pos = pos[max(earlier)]
            for i, d in enumerate(all_days):
                if d in pos:
                    last_pos = pos[d]
                v = cash[d] + last_pos
                r = rates.get(d)
                if d < opened:
                    values.append(None)
                    continue
                if r is None:
                    values.append(None)
                    complete[i] = False
                    continue
                eur = v * r
                values.append(eur)
                total[i] += eur
            if acc["archived"] and all(v in (None, ZERO) for v in values):
                continue
            lines.append({"id": acc["id"], "name": acc["name"], "currency": cur, "archived": bool(acc["archived"]),
                          "value": values})
    idx = investments._downsample(all_days, max_points)
    rnd = lambda v: None if v is None else round(float(v), 2)  # noqa: E731
    return {
        "range": range_key,
        "dates": [all_days[i].isoformat() for i in idx],
        "total": [rnd(total[i]) for i in idx],
        "complete": all(complete),
        "accounts": [{**ln, "value": [rnd(ln["value"][i]) for i in idx]} for ln in lines],
    }
