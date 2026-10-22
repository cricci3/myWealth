"""Exchange rates towards EUR: Yahoo daily history cached in `fx_rates`, manual rates,
offline fallback, and the per-operation snapshot.

A rate is "EUR per one unit of the currency" (Yahoo `CHFEUR=X`). For a given day the
rate used is the one of that day or, if missing (weekend, holiday, no connection), the
most recent one before it. Only when no earlier rate exists at all is the nearest later
one used, so an operation always gets a EUR value as soon as any rate is known.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, timedelta
from decimal import Decimal

from . import market, money
from .db import Database
from .errors import ValidationError
from .money import BASE

log = logging.getLogger(__name__)

HISTORY_MARGIN_DAYS = 7  # fetch a few days before the oldest date, to cover weekends


# ---------------------------------------------------------------------- lookup


def snapshot(conn: sqlite3.Connection, currency: str, day: str) -> tuple[str | None, str | None]:
    """(rate, rate date) of `currency` -> EUR to store on an operation dated `day`."""
    if currency == BASE:
        return "1", day
    row = conn.execute(
        "SELECT rate, date FROM fx_rates WHERE currency = ? AND date <= ? ORDER BY date DESC LIMIT 1",
        (currency, day),
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT rate, date FROM fx_rates WHERE currency = ? AND date > ? ORDER BY date LIMIT 1", (currency, day)
        ).fetchone()
    return (row[0], row[1]) if row else (None, None)


def rate_on(conn: sqlite3.Connection, currency: str, day: str) -> Decimal | None:
    rate, _ = snapshot(conn, currency, day)
    return Decimal(rate) if rate is not None else None


def latest(conn: sqlite3.Connection) -> dict[str, dict]:
    """Most recent known rate per currency."""
    rows = conn.execute(
        """SELECT f.currency, f.rate, f.date, f.source FROM fx_rates f
           JOIN (SELECT currency, MAX(date) AS d FROM fx_rates GROUP BY currency) m
             ON m.currency = f.currency AND m.d = f.date"""
    ).fetchall()
    return {r["currency"]: {"rate": r["rate"], "date": r["date"], "source": r["source"]} for r in rows}


def latest_rate(conn: sqlite3.Connection, currency: str) -> Decimal | None:
    if currency == BASE:
        return Decimal(1)
    return rate_on(conn, currency, "9999-12-31")


def daily_series(conn: sqlite3.Connection, currency: str, start: date, end: date) -> dict[date, Decimal | None]:
    """Rate for every calendar day in [start, end] with the same fallback as snapshot()."""
    out: dict[date, Decimal | None] = {}
    if currency == BASE:
        d = start
        while d <= end:
            out[d] = Decimal(1)
            d += timedelta(days=1)
        return out
    rows = conn.execute(
        "SELECT date, rate FROM fx_rates WHERE currency = ? AND date <= ? ORDER BY date", (currency, end.isoformat())
    ).fetchall()
    known = [(date.fromisoformat(r[0]), Decimal(r[1])) for r in rows]
    first_after = None
    if not known or known[0][0] > start:
        r = conn.execute("SELECT rate FROM fx_rates WHERE currency = ? ORDER BY date LIMIT 1", (currency,)).fetchone()
        first_after = Decimal(r[0]) if r else None
    i, current = 0, first_after
    d = start
    while d <= end:
        while i < len(known) and known[i][0] <= d:
            current = known[i][1]
            i += 1
        out[d] = current
        d += timedelta(days=1)
    return out


# --------------------------------------------------------------------- refresh


def needed_currencies(conn: sqlite3.Connection) -> dict[str, str]:
    """Non-EUR currencies in use -> oldest date a rate is needed for."""
    needed: dict[str, str] = {}

    def add(cur: str, day: str | None) -> None:
        if cur and cur != BASE and day:
            needed[cur] = min(needed.get(cur, day), day)

    for cur, day in conn.execute("SELECT currency, MIN(opened_on) FROM accounts GROUP BY currency"):
        add(cur, day)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'assets'").fetchone():
        for cur, day in conn.execute(
            "SELECT a.currency, MIN(t.date) FROM assets a JOIN asset_trades t ON t.asset_id = a.id"
            " GROUP BY a.currency"
        ):
            add(market.normalize_currency(cur)[0], day)
    return needed


def fetch_start(conn: sqlite3.Connection, symbol: str, needed: date, today: date, force: bool = False) -> date | None:
    """Start date for the next download of `symbol`, or None if it isn't due.

    At most one download per symbol per day; a second one happens only if older history
    is needed than what was downloaded (e.g. a new operation in the past).
    """
    needed = needed - timedelta(days=HISTORY_MARGIN_DAYS)
    row = conn.execute("SELECT fetched_on, start FROM market_fetch WHERE symbol = ?", (symbol,)).fetchone()
    if row is None or not row["fetched_on"]:
        return needed
    covered = date.fromisoformat(row["start"])
    if needed < covered:
        return needed
    if row["fetched_on"] == today.isoformat() and not force:
        return None
    last = date.fromisoformat(row["fetched_on"]) - timedelta(days=HISTORY_MARGIN_DAYS)
    return max(min(last, today), covered)


def record_fetch(conn: sqlite3.Connection, symbol: str, start: date | None, today: date, error: str | None) -> None:
    row = conn.execute("SELECT fetched_on, start FROM market_fetch WHERE symbol = ?", (symbol,)).fetchone()
    if error is not None:
        if row:
            conn.execute("UPDATE market_fetch SET error = ? WHERE symbol = ?", (error, symbol))
        else:
            conn.execute("INSERT INTO market_fetch (symbol, fetched_on, start, error) VALUES (?, '', ?, ?)",
                         (symbol, today.isoformat(), error))
        return
    new_start = start.isoformat()
    if row and row["fetched_on"]:
        new_start = min(new_start, row["start"])
    conn.execute(
        "INSERT INTO market_fetch (symbol, fetched_on, start, error) VALUES (?, ?, ?, NULL)"
        " ON CONFLICT(symbol) DO UPDATE SET fetched_on = excluded.fetched_on, start = excluded.start, error = NULL",
        (symbol, today.isoformat(), new_start),
    )


def store_rates(conn: sqlite3.Connection, currency: str, rows: list[tuple[date, Decimal]], source: str) -> int:
    """Save downloaded rates; a manual rate for the same day is never overwritten."""
    conn.executemany(
        "INSERT INTO fx_rates (currency, date, rate, source) VALUES (?, ?, ?, ?)"
        " ON CONFLICT(currency, date) DO UPDATE SET rate = excluded.rate, source = excluded.source"
        " WHERE fx_rates.source != 'manual'",
        [(currency, d.isoformat(), str(r), source) for d, r in rows],
    )
    return len(rows)


def refresh(db: Database, provider: market.Provider, force: bool = False, today: date | None = None) -> dict:
    """Download missing rates for every currency in use. Never raises for network errors:
    they are reported per currency and the last saved rate keeps being used."""
    today = today or date.today()
    with db.connect() as conn:
        needed = needed_currencies(conn)
    result = {"updated": [], "errors": {}, "skipped": []}
    source = "demo" if provider.name == "demo" else "yahoo"
    for currency, oldest in sorted(needed.items()):
        symbol = market.fx_symbol(currency)
        with db.connect() as conn:
            start = fetch_start(conn, symbol, date.fromisoformat(oldest), today, force)
        if start is None:
            result["skipped"].append(currency)
            continue
        try:
            rows = provider.history(symbol, start)
        except market.MarketError as e:
            log.info("FX %s not updated: %s", currency, e)
            result["errors"][currency] = str(e)
            with db.transaction() as conn:
                record_fetch(conn, symbol, None, today, str(e))
            continue
        with db.transaction() as conn:
            store_rates(conn, currency, rows, source)
            record_fetch(conn, symbol, start, today, None)
        result["updated"].append(currency)
    if result["updated"]:
        with db.transaction() as conn:
            resnapshot(conn)
    return result


def resnapshot(conn: sqlite3.Connection) -> int:
    """Fill or improve operation rates that aren't the rate of their own day.

    Rates of operations whose snapshot is already the one of their date are never
    touched: a later change in the stored rates doesn't rewrite the past.
    """
    changed = 0
    rows = conn.execute(
        """SELECT t.id, t.date, t.from_rate, t.from_rate_date, t.to_rate, t.to_rate_date,
                  fa.currency AS from_cur, ta.currency AS to_cur
           FROM transactions t
           LEFT JOIN accounts fa ON fa.id = t.from_account_id
           LEFT JOIN accounts ta ON ta.id = t.to_account_id
           WHERE (t.from_account_id IS NOT NULL AND (t.from_rate IS NULL OR t.from_rate_date != t.date))
              OR (t.to_account_id IS NOT NULL AND (t.to_rate IS NULL OR t.to_rate_date != t.date))"""
    ).fetchall()
    for r in rows:
        updates = {}
        for side in ("from", "to"):
            cur = r[f"{side}_cur"]
            if cur is None:
                continue
            rate, rate_date = snapshot(conn, cur, r["date"])
            if (rate, rate_date) != (r[f"{side}_rate"], r[f"{side}_rate_date"]) and rate is not None:
                updates[f"{side}_rate"] = rate
                updates[f"{side}_rate_date"] = rate_date
        if updates:
            sets = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(f"UPDATE transactions SET {sets} WHERE id = ?", (*updates.values(), r["id"]))
            changed += 1
    return changed


# ---------------------------------------------------------------------- manual


def add_manual(db: Database, data: dict) -> dict:
    currency = money.check_currency(data.get("currency"))
    if currency == BASE:
        raise ValidationError("Il cambio EUR → EUR è sempre 1.")
    day = money.parse_date(data.get("date") or date.today().isoformat())
    if day > date.today():
        raise ValidationError("La data non può essere nel futuro.")
    rate = money.parse_decimal(data.get("rate"), "tasso")
    if rate <= 0:
        raise ValidationError("Il tasso deve essere maggiore di zero.")
    if data.get("direction") == "per_eur":  # entered as "1 EUR = x CUR"
        rate = (Decimal(1) / rate).quantize(Decimal("1e-10")).normalize()
    rate_text = format(rate, "f")
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO fx_rates (currency, date, rate, source) VALUES (?, ?, ?, 'manual')"
            " ON CONFLICT(currency, date) DO UPDATE SET rate = excluded.rate, source = 'manual'",
            (currency, day.isoformat(), rate_text),
        )
        resnapshot(conn)
    return {"currency": currency, "date": day.isoformat(), "rate": rate_text, "source": "manual"}


def delete_manual(db: Database, currency: str, day: str) -> None:
    with db.transaction() as conn:
        n = conn.execute(
            "DELETE FROM fx_rates WHERE currency = ? AND date = ? AND source = 'manual'", (currency, day)
        ).rowcount
        if not n:
            raise ValidationError("Tasso manuale non trovato.")
        # operations that used it get the best remaining rate
        conn.execute(
            "UPDATE transactions SET from_rate = NULL, from_rate_date = NULL WHERE from_rate_date = ?"
            " AND from_account_id IN (SELECT id FROM accounts WHERE currency = ?)", (day, currency))
        conn.execute(
            "UPDATE transactions SET to_rate = NULL, to_rate_date = NULL WHERE to_rate_date = ?"
            " AND to_account_id IN (SELECT id FROM accounts WHERE currency = ?)", (day, currency))
        resnapshot(conn)


def rates_list(db: Database, currency: str | None = None, limit: int = 60) -> list[dict]:
    with db.connect() as conn:
        if currency:
            rows = conn.execute(
                "SELECT * FROM fx_rates WHERE currency = ? ORDER BY date DESC LIMIT ?", (currency, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM fx_rates WHERE source = 'manual' ORDER BY date DESC LIMIT ?", (limit,)
            ).fetchall()
    return [dict(r) for r in rows]


def status(db: Database, today: date | None = None) -> dict:
    """Latest rate per currency in use, with its age and the last download error."""
    today = today or date.today()
    with db.connect() as conn:
        needed = needed_currencies(conn)
        last = latest(conn)
        fetches = {r["symbol"]: dict(r) for r in conn.execute("SELECT * FROM market_fetch")}
    out = {}
    for cur in sorted(set(needed) | set(last)):
        info = last.get(cur)
        f = fetches.get(market.fx_symbol(cur), {})
        out[cur] = {
            "rate": info and info["rate"],
            "date": info and info["date"],
            "source": info and info["source"],
            "fetched_on": f.get("fetched_on") or None,
            "error": f.get("error"),
            # stale: no rate from the last 4 days (allows for weekends and holidays)
            "stale": info is None or info["date"] < (today - timedelta(days=4)).isoformat(),
        }
    return out
