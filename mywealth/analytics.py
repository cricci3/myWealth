"""Analytics, in EUR at each operation's own rate (snapshot).

Expenses = 'expense' + 'fee' operations; income = 'income' + 'interest'. Transfers
between own accounts and asset buys/sells are neither: they only move money around.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from . import home, money
from .db import Database
from .errors import ValidationError

ZERO = Decimal(0)
EXPENSE_KINDS = ("expense", "fee")
INCOME_KINDS = ("income", "interest")


def _period(start, end) -> tuple[str, str]:
    s = money.parse_date(start, "data iniziale")
    e = money.parse_date(end, "data finale")
    if e < s:
        raise ValidationError("La data finale è precedente a quella iniziale.")
    return s.isoformat(), e.isoformat()


def _month_add(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def _eur(minor: int | None, cur: str | None, rate: str | None) -> Decimal | None:
    if minor is None or rate is None or cur is None:
        return None
    return money.from_minor(minor, cur) * Decimal(rate)


def expenses_by_category(db: Database, start, end, account_id=None) -> dict:
    s, e = _period(start, end)
    args: list = [s, e]
    cond = ""
    if account_id not in (None, ""):
        cond = "AND t.from_account_id = ?"
        try:
            args.append(int(account_id))
        except ValueError:
            raise ValidationError("Conto non valido.") from None
    with db.connect() as conn:
        rows = conn.execute(
            f"""SELECT t.category_id, c.name, t.from_amount, t.from_rate, a.currency
                FROM transactions t JOIN accounts a ON a.id = t.from_account_id
                LEFT JOIN categories c ON c.id = t.category_id
                WHERE t.kind IN ('expense', 'fee') AND t.date BETWEEN ? AND ? {cond}""",
            args,
        ).fetchall()
    totals: dict = defaultdict(lambda: ZERO)
    names: dict = {}
    missing = 0
    for r in rows:
        v = _eur(r["from_amount"], r["currency"], r["from_rate"])
        if v is None:
            missing += 1
            continue
        totals[r["category_id"]] += v
        names[r["category_id"]] = r["name"] or "Senza categoria"
    items = sorted(totals.items(), key=lambda kv: -kv[1])
    total = sum(totals.values(), ZERO)
    return {
        "from": s, "to": e, "total": money.fmt_decimal(total), "missing": missing,
        "items": [{"category_id": k, "name": names[k], "eur": money.fmt_decimal(v)} for k, v in items],
    }


def monthly(db: Database, year: int | None = None, months: int = 12, today: date | None = None) -> dict:
    """Income vs expenses per month (EUR), with the savings rate."""
    today = today or date.today()
    if year:
        first = date(int(year), 1, 1)
        n = 12
    else:
        n = max(1, min(int(months), 120))
        first = _month_add(today.replace(day=1), -(n - 1))
    last = _month_add(first, n) - timedelta(days=1)
    keys = [_month_add(first, i).strftime("%Y-%m") for i in range(n)]
    inc = {k: ZERO for k in keys}
    exp = {k: ZERO for k in keys}
    missing = 0
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT t.kind, t.date, t.from_amount, t.from_rate, fa.currency AS fcur,
                      t.to_amount, t.to_rate, ta.currency AS tcur
               FROM transactions t
               LEFT JOIN accounts fa ON fa.id = t.from_account_id
               LEFT JOIN accounts ta ON ta.id = t.to_account_id
               WHERE t.kind IN ('expense', 'fee', 'income', 'interest') AND t.date BETWEEN ? AND ?""",
            (first.isoformat(), last.isoformat()),
        ).fetchall()
    for r in rows:
        k = r["date"][:7]
        if r["kind"] in EXPENSE_KINDS:
            v = _eur(r["from_amount"], r["fcur"], r["from_rate"])
            target = exp
        else:
            v = _eur(r["to_amount"], r["tcur"], r["to_rate"])
            target = inc
        if v is None:
            missing += 1
            continue
        target[k] += v
    out = []
    for k in keys:
        i, x = inc[k], exp[k]
        out.append({
            "month": k, "income": money.fmt_decimal(i), "expenses": money.fmt_decimal(x),
            "net": money.fmt_decimal(i - x),
            "savings_rate": float((i - x) / i * 100) if i > 0 else None,
        })
    ti = sum(inc.values(), ZERO)
    tx = sum(exp.values(), ZERO)
    return {
        "months": out, "missing": missing,
        "total": {"income": money.fmt_decimal(ti), "expenses": money.fmt_decimal(tx), "net": money.fmt_decimal(ti - tx),
                  "savings_rate": float((ti - tx) / ti * 100) if ti > 0 else None},
    }


def account_report(db: Database, start, end) -> dict:
    """Per account in the period: income, expenses, transfers (net), invested (buys − sells),
    in the account currency and in EUR."""
    s, e = _period(start, end)
    with db.connect() as conn:
        accs = conn.execute(
            "SELECT a.id, a.name, a.currency, a.archived, t.behavior FROM accounts a"
            " JOIN account_types t ON t.id = a.type_id ORDER BY a.archived, a.name COLLATE NOCASE"
        ).fetchall()
        rows = conn.execute(
            """SELECT kind, from_account_id, to_account_id, from_amount, to_amount, from_rate, to_rate
               FROM transactions WHERE date BETWEEN ? AND ?""",
            (s, e),
        ).fetchall()
    cur = {a["id"]: a["currency"] for a in accs}
    zero = lambda: {"minor": 0, "eur": ZERO, "missing": False}  # noqa: E731
    data = {a["id"]: {k: zero() for k in ("income", "expenses", "transfers", "invested")} for a in accs}

    def add(acc_id, col, minor, rate, sign=1):
        cell = data[acc_id][col]
        cell["minor"] += sign * minor
        v = _eur(minor, cur[acc_id], rate)
        if v is None:
            cell["missing"] = True
        else:
            cell["eur"] += sign * v

    for r in rows:
        k = r["kind"]
        if k in INCOME_KINDS:
            add(r["to_account_id"], "income", r["to_amount"], r["to_rate"])
        elif k in EXPENSE_KINDS:
            add(r["from_account_id"], "expenses", r["from_amount"], r["from_rate"])
        elif k == "transfer":
            add(r["to_account_id"], "transfers", r["to_amount"], r["to_rate"])
            add(r["from_account_id"], "transfers", r["from_amount"], r["from_rate"], -1)
        elif k == "buy":
            add(r["from_account_id"], "invested", r["from_amount"], r["from_rate"])
        elif k == "sell":
            add(r["to_account_id"], "invested", r["to_amount"], r["to_rate"], -1)

    out = []
    totals = {k: ZERO for k in ("income", "expenses", "transfers", "invested")}
    for a in accs:
        d = data[a["id"]]
        if a["archived"] and all(c["minor"] == 0 for c in d.values()):
            continue
        row = {"id": a["id"], "name": a["name"], "currency": a["currency"], "behavior": a["behavior"]}
        for col, cell in d.items():
            row[col] = money.fmt(cell["minor"], a["currency"])
            row[f"{col}_eur"] = None if cell["missing"] else money.fmt_decimal(cell["eur"])
            totals[col] += cell["eur"]
        out.append(row)
    return {"from": s, "to": e, "accounts": out, "totals": {k: money.fmt_decimal(v) for k, v in totals.items()}}


def net_worth(db: Database, today: date | None = None) -> dict:
    """Net worth in EUR at the end of every month (and today)."""
    h = home.history(db, "max", today, max_points=100_000)
    if not h["dates"]:
        return {"points": []}
    by_month: dict[str, tuple[str, float]] = {}
    for d, v in zip(h["dates"], h["total"]):
        by_month[d[:7]] = (d, v)  # last day of each month present in the series
    return {"points": [{"date": d, "month": m, "eur": v} for m, (d, v) in sorted(by_month.items())]}
