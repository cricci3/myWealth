"""Savings accounts: annual yield with history and monthly interest generation.

Interest accrues every day on the end-of-day balance:
    daily interest = balance × annual rate % / 12 / days in the month
using the rate valid on that day (a negative balance earns nothing). The month's total
is rounded once and credited as an automatic `interest` operation on the last day of
the month, net of the optional withholding tax. Each computed month is recorded in
`interest_runs`, so running the generation again never creates duplicates and an
interest operation deleted or edited by the user is left alone.
"""

from __future__ import annotations

import calendar
import sqlite3
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from . import accounts, categories, money, settings, transactions
from .db import Database, now_iso
from .errors import ConflictError, NotFoundError, ValidationError

MONTHS_IT = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
             "ottobre", "novembre", "dicembre"]
MAX_RATE = Decimal(100)


def _savings_account(conn: sqlite3.Connection, account_id) -> sqlite3.Row:
    acc = accounts.account_row(conn, account_id)
    if acc["behavior"] != "savings":
        raise ValidationError("Il rendimento si imposta solo sui conti di tipo salvadanaio.")
    return acc


# ------------------------------------------------------------------------ rates


def list_rates(db: Database, account_id: int) -> list[dict]:
    with db.connect() as conn:
        _savings_account(conn, account_id)
        rows = conn.execute(
            "SELECT id, annual_rate, valid_from FROM savings_rates WHERE account_id = ? ORDER BY valid_from",
            (account_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def current_rates(conn: sqlite3.Connection, day: str | None = None) -> dict[int, str]:
    """account id -> annual rate valid on `day` (today by default)."""
    day = day or date.today().isoformat()
    rows = conn.execute(
        """SELECT r.account_id, r.annual_rate FROM savings_rates r
           WHERE r.valid_from = (SELECT MAX(valid_from) FROM savings_rates x
                                 WHERE x.account_id = r.account_id AND x.valid_from <= ?)""",
        (day,),
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def add_rate(db: Database, account_id: int, data: dict) -> dict:
    rate = money.parse_decimal(data.get("annual_rate"), "rendimento", max_places=4)
    if rate < 0 or rate > MAX_RATE:
        raise ValidationError("Il rendimento deve essere tra 0 e 100%.")
    with db.transaction() as conn:
        acc = _savings_account(conn, account_id)
        valid_from = money.parse_date(data.get("valid_from") or date.today().isoformat(), "data di validità")
        valid_from = max(valid_from.isoformat(), acc["opened_on"])
        conn.execute(
            "INSERT INTO savings_rates (account_id, annual_rate, valid_from) VALUES (?, ?, ?)"
            " ON CONFLICT(account_id, valid_from) DO UPDATE SET annual_rate = excluded.annual_rate",
            (account_id, format(rate.normalize(), "f"), valid_from),
        )
    return {"account_id": account_id, "annual_rate": format(rate.normalize(), "f"), "valid_from": valid_from}


def delete_rate(db: Database, account_id: int, rate_id: int) -> None:
    with db.transaction() as conn:
        n = conn.execute("DELETE FROM savings_rates WHERE id = ? AND account_id = ?", (rate_id, account_id)).rowcount
        if not n:
            raise NotFoundError("Tasso non trovato.")


# ------------------------------------------------------------------- generation


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _next_month(d: date) -> date:
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def compute_month(conn: sqlite3.Connection, account_id: int, year: int, month: int) -> int:
    """Gross interest (minor units) earned in the month, before rounding to the credit."""
    acc = accounts.account_row(conn, account_id)
    cur = acc["currency"]
    first, last = date(year, month, 1), _month_end(year, month)
    days_in_month = Decimal(last.day)

    rates = conn.execute(
        "SELECT valid_from, annual_rate FROM savings_rates WHERE account_id = ? AND valid_from <= ?"
        " ORDER BY valid_from",
        (account_id, last.isoformat()),
    ).fetchall()
    if not rates:
        return 0

    opened = date.fromisoformat(acc["opened_on"])
    bal = accounts.balance(conn, account_id, (first - timedelta(days=1)).isoformat()) if opened < first else 0
    moves: dict[str, int] = {}
    for d, amount in conn.execute(
        """SELECT date, SUM(CASE WHEN to_account_id = ? THEN to_amount ELSE 0 END)
                      - SUM(CASE WHEN from_account_id = ? THEN from_amount ELSE 0 END)
           FROM transactions WHERE (from_account_id = ? OR to_account_id = ?) AND date BETWEEN ? AND ?
           GROUP BY date""",
        (account_id, account_id, account_id, account_id, first.isoformat(), last.isoformat()),
    ):
        moves[d] = amount

    total = Decimal(0)
    ri, rate = 0, Decimal(0)
    d = first
    while d <= last:
        iso = d.isoformat()
        while ri < len(rates) and rates[ri]["valid_from"] <= iso:
            rate = Decimal(rates[ri]["annual_rate"])
            ri += 1
        if d == opened:
            bal = acc["opening_balance"]
        if d >= opened:
            bal += moves.get(iso, 0)
            if bal > 0 and rate > 0:
                total += money.from_minor(bal, cur) * rate  # exact: divided once below
        d += timedelta(days=1)
    return money.to_minor(total / (100 * 12 * days_in_month), cur)


def _tax(conn: sqlite3.Connection, prefs: dict, gross: int) -> int:
    if not prefs["interest_tax_enabled"] or gross <= 0:
        return 0
    rate = Decimal(prefs["interest_tax_rate"])
    return int((Decimal(gross) * rate / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def generate(db: Database, today: date | None = None, account_id: int | None = None) -> list[dict]:
    """Create the interest of every completed month not computed yet. Idempotent."""
    today = today or date.today()
    this_month = today.replace(day=1)
    prefs = settings.load(db)
    created = []
    with db.transaction() as conn:
        rows = conn.execute(
            """SELECT a.id, a.name, a.currency, a.opened_on FROM accounts a JOIN account_types t ON t.id = a.type_id
               WHERE t.behavior = 'savings' AND a.archived = 0"""
        ).fetchall()
        cat = categories.system_category(conn, "interest")
        for acc in rows:
            if account_id is not None and acc["id"] != account_id:
                continue
            first_rate = conn.execute(
                "SELECT MIN(valid_from) FROM savings_rates WHERE account_id = ?", (acc["id"],)
            ).fetchone()[0]
            if not first_rate:
                continue
            m = date.fromisoformat(max(acc["opened_on"], first_rate)).replace(day=1)
            done = {r[0] for r in conn.execute("SELECT month FROM interest_runs WHERE account_id = ?", (acc["id"],))}
            while m < this_month:
                key = m.strftime("%Y-%m")
                if key not in done:
                    created.append(_credit(conn, acc, m, cat, prefs))
                m = _next_month(m)
    return [c for c in created if c]


def _credit(conn: sqlite3.Connection, acc: sqlite3.Row, m: date, cat: int, prefs: dict) -> dict | None:
    gross = compute_month(conn, acc["id"], m.year, m.month)
    tax = _tax(conn, prefs, gross)
    net = gross - tax
    tx_id = None
    last = _month_end(m.year, m.month)
    if net > 0:
        label = f"Interessi {MONTHS_IT[m.month - 1]} {m.year}"
        if tax:
            label += (f" (lordo {money.fmt(gross, acc['currency'])}, ritenuta "
                      f"{money.fmt(tax, acc['currency'])} {acc['currency']})")
        tx_id = transactions.write(conn, {
            "kind": "interest", "date": last.isoformat(), "to_account_id": acc["id"], "to_amount": net,
            "category_id": cat, "description": label, "auto": 1,
        })
    conn.execute(
        "INSERT INTO interest_runs (account_id, month, transaction_id, gross, tax, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (acc["id"], m.strftime("%Y-%m"), tx_id, gross, tax, now_iso()),
    )
    if tx_id is None:
        return None
    return {"account_id": acc["id"], "month": m.strftime("%Y-%m"), "amount": money.fmt(net, acc["currency"]),
            "transaction_id": tx_id}


def recalculate(db: Database, account_id: int, from_month: str, today: date | None = None) -> list[dict]:
    """Delete the generated interest from `from_month` (YYYY-MM) on and compute it again,
    e.g. after adding a rate or an operation in the past. Edited amounts are lost."""
    try:
        start = date.fromisoformat(f"{from_month}-01")
    except (TypeError, ValueError):
        raise ValidationError("Mese non valido.") from None
    with db.transaction() as conn:
        acc = _savings_account(conn, account_id)
        if acc["archived"]:
            raise ConflictError("Il conto è archiviato.")
        key = start.strftime("%Y-%m")
        conn.execute(
            "DELETE FROM transactions WHERE id IN (SELECT transaction_id FROM interest_runs"
            " WHERE account_id = ? AND month >= ?)",
            (account_id, key),
        )
        conn.execute("DELETE FROM interest_runs WHERE account_id = ? AND month >= ?", (account_id, key))
    return generate(db, today, account_id)


def overview(db: Database, account_id: int) -> dict:
    with db.connect() as conn:
        acc = _savings_account(conn, account_id)
        runs = conn.execute(
            """SELECT r.month, r.gross, r.tax, r.transaction_id, t.to_amount AS credited
               FROM interest_runs r LEFT JOIN transactions t ON t.id = r.transaction_id
               WHERE r.account_id = ? ORDER BY r.month DESC LIMIT 24""",
            (account_id,),
        ).fetchall()
        cur = acc["currency"]
        current = current_rates(conn).get(account_id)
    return {
        "account_id": account_id,
        "current_rate": current,
        "rates": list_rates(db, account_id),
        "months": [{
            "month": r["month"],
            "gross": money.fmt(r["gross"], cur),
            "tax": money.fmt(r["tax"], cur),
            "credited": money.fmt(r["credited"], cur) if r["credited"] is not None else None,
            "transaction_id": r["transaction_id"],
        } for r in runs],
    }
