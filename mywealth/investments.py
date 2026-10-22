"""Investment accounts: assets, buys and sells, valuation and returns.

Ported from PortfolioTracker (portfolio.py, MIT, same author) and adapted:
- amounts are in the currency of the investment account (not always EUR) and stored in
  minor units; valuation uses Decimal;
- the account balance is the liquidity: a buy moves money from it into a position and is
  blocked when the liquidity isn't enough; a sell gives the proceeds back;
- sells are recorded with the number of shares sold and the proceeds; the cost of the
  shares sold leaves the invested capital at average cost, the rest is realized gain;
- buy/sell fees are ordinary expenses ('fee' operations) and don't enter the returns.

Shares bought = amount / price on the first trading day >= the buy date (converted to
the account currency with that day's rates), unless the user entered the actual unit
price or number of shares.

Metrics: annual return = XIRR (money-weighted), last 12 months = Modified Dietz.
"""

from __future__ import annotations

import bisect
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from . import accounts, categories, fx, market, money, transactions
from .db import Database, now_iso
from .errors import ConflictError, NotFoundError, ValidationError

MAX_POINTS = 360
MIN_DAYS_FOR_ANNUALIZED = 180
SHARES_PLACES = 8
ZERO = Decimal(0)
TOLERANCE = Decimal("1e-6")


# =============================================================== prices (cache)


def needed_tickers(conn: sqlite3.Connection) -> dict[str, str]:
    """ticker -> oldest trade date, for every asset with at least one trade."""
    return {r[0]: r[1] for r in conn.execute(
        "SELECT a.ticker, MIN(t.date) FROM assets a JOIN asset_trades t ON t.asset_id = a.id GROUP BY a.ticker"
    )}


def refresh_prices(db: Database, provider: market.Provider, force: bool = False, today: date | None = None,
                   tickers: list[str] | None = None) -> dict:
    """Download missing closes (at most once per ticker per day unless forced). Errors are
    reported per ticker; the cached prices keep being used."""
    today = today or date.today()
    with db.connect() as conn:
        needed = needed_tickers(conn)
    if tickers is not None:
        needed = {t: d for t, d in needed.items() if t in tickers}
    result = {"updated": [], "errors": {}, "skipped": []}
    for ticker, oldest in sorted(needed.items()):
        # the 12-month metrics need a year of prices even for a recent asset
        start = min(date.fromisoformat(oldest), today - timedelta(days=380))
        with db.connect() as conn:
            fetch_from = fx.fetch_start(conn, ticker, start, today, force)
        if fetch_from is None:
            result["skipped"].append(ticker)
            continue
        try:
            rows = provider.history(ticker, fetch_from)
        except market.MarketError as e:
            result["errors"][ticker] = str(e)
            with db.transaction() as conn:
                fx.record_fetch(conn, ticker, None, today, str(e))
            continue
        with db.transaction() as conn:
            conn.executemany(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)"
                " ON CONFLICT(ticker, date) DO UPDATE SET close = excluded.close",
                [(ticker, d.isoformat(), str(p)) for d, p in rows],
            )
            fx.record_fetch(conn, ticker, fetch_from, today, None)
        result["updated"].append(ticker)
    return result


class PriceSeries:
    """Closes of one ticker in its ISO currency (pence -> pounds), with lookups by day."""

    def __init__(self, conn: sqlite3.Connection, ticker: str, quote_currency: str):
        self.currency, divisor = market.normalize_currency(quote_currency)
        rows = conn.execute("SELECT date, close FROM prices WHERE ticker = ? ORDER BY date", (ticker,)).fetchall()
        self.days = [date.fromisoformat(r[0]) for r in rows]
        self.closes = [Decimal(r[1]) / divisor for r in rows]

    def __bool__(self) -> bool:
        return bool(self.days)

    def on_or_before(self, d: date) -> tuple[date, Decimal] | None:
        i = bisect.bisect_right(self.days, d) - 1
        return (self.days[i], self.closes[i]) if i >= 0 else None

    def on_or_after(self, d: date) -> tuple[date, Decimal] | None:
        i = bisect.bisect_left(self.days, d)
        return (self.days[i], self.closes[i]) if i < len(self.days) else None

    @property
    def last(self) -> tuple[date, Decimal] | None:
        return (self.days[-1], self.closes[-1]) if self.days else None


class FxConverter:
    """Factor from the instrument currency to the account currency on a day."""

    def __init__(self, conn: sqlite3.Connection, src: str, dst: str, start: date, end: date):
        self.same = src == dst
        if not self.same:
            self.a = fx.daily_series(conn, src, start, end)
            self.b = fx.daily_series(conn, dst, start, end)
            self.start, self.end = start, end
            self.src, self.dst = src, dst
            self._conn = conn

    def factor(self, d: date) -> Decimal | None:
        if self.same:
            return Decimal(1)
        if d < self.start or d > self.end:
            a = fx.rate_on(self._conn, self.src, d.isoformat())
            b = fx.rate_on(self._conn, self.dst, d.isoformat())
        else:
            a, b = self.a.get(d), self.b.get(d)
        if a is None or b is None or b == 0:
            return None
        return a / b


# ===================================================================== metrics


def xirr(cashflows: list[tuple[date, float]]) -> float | None:
    """Annual internal rate of return for irregular cash flows (robust bisection).
    Floats are fine here: it is a rate, not an amount."""
    if len(cashflows) < 2:
        return None
    t0 = min(d for d, _ in cashflows)
    flows = [((d - t0).days / 365.25, v) for d, v in cashflows]

    def npv(r: float) -> float:
        return sum(v / (1 + r) ** t for t, v in flows)

    lo, hi = -0.9999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-7:
            break
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def _downsample(days: list[date], max_points: int = MAX_POINTS) -> list[int]:
    n = len(days)
    if n <= max_points:
        return list(range(n))
    step = n / max_points
    return sorted({int(i * step) for i in range(max_points)} | {n - 1})


def _pct(num: Decimal, den: Decimal) -> float | None:
    return float(num / den * 100) if den else None


@dataclass
class Trade:
    id: int
    kind: str
    date: date
    amount: Decimal  # account currency
    amount_minor: int
    shares_input: Decimal | None
    price_input: Decimal | None
    note: str
    transaction_id: int | None
    fee_transaction_id: int | None
    fee: Decimal | None
    # resolved
    shares: Decimal | None = None
    exec_date: date | None = None
    exec_price: Decimal | None = None  # account currency per share


def _load_trades(conn: sqlite3.Connection, asset_id: int, cur: str) -> list[Trade]:
    rows = conn.execute(
        """SELECT t.*, f.from_amount AS fee_amount FROM asset_trades t
           LEFT JOIN transactions f ON f.id = t.fee_transaction_id
           WHERE t.asset_id = ? ORDER BY t.date, t.kind = 'sell', t.id""",
        (asset_id,),
    ).fetchall()
    return [
        Trade(
            id=r["id"], kind=r["kind"], date=date.fromisoformat(r["date"]),
            amount=money.from_minor(r["amount"], cur), amount_minor=r["amount"],
            shares_input=Decimal(r["shares"]) if r["shares"] else None,
            price_input=Decimal(r["price"]) if r["price"] else None,
            note=r["note"], transaction_id=r["transaction_id"], fee_transaction_id=r["fee_transaction_id"],
            fee=money.from_minor(r["fee_amount"], cur) if r["fee_amount"] is not None else None,
        )
        for r in rows
    ]


def compute_asset(conn: sqlite3.Connection, asset: sqlite3.Row, acc_cur: str, today: date | None = None) -> dict:
    """Valuation and returns of one asset, in the account currency."""
    today = today or date.today()
    trades = _load_trades(conn, asset["id"], acc_cur)
    out: dict = {
        "id": asset["id"], "ticker": asset["ticker"], "name": asset["name"], "exchange": asset["exchange"],
        "currency": market.normalize_currency(asset["currency"])[0], "quote_currency": asset["currency"],
        "input_symbol": asset["input_symbol"], "error": None, "trades": [],
    }
    if not trades:
        out["error"] = "Nessuna operazione registrata."
        return out

    prices = PriceSeries(conn, asset["ticker"], asset["currency"])
    first = trades[0].date
    end = max(today, prices.last[0]) if prices else today
    conv = FxConverter(conn, prices.currency, acc_cur, min(first, today - timedelta(days=380)) - timedelta(days=10), end)

    # --- resolve the shares of every trade --------------------------------------
    problems = []
    for t in trades:
        if t.kind == "sell":
            t.shares = t.shares_input
            t.exec_date = t.date
            t.exec_price = t.amount / t.shares if t.shares else None
            continue
        hit = prices.on_or_after(t.date) or prices.on_or_before(t.date)
        # a buy dated today, before the first close, uses the last price but stays on its day
        t.exec_date = max(hit[0], t.date) if hit else t.date
        if t.shares_input:
            t.shares = t.shares_input
            t.exec_price = t.amount / t.shares
        elif t.price_input:
            f = conv.factor(t.exec_date)
            if f is None:
                problems.append(f"cambio {prices.currency}/{acc_cur} non disponibile")
                continue
            t.exec_price = t.price_input * f
            t.shares = t.amount / t.exec_price
        elif hit:
            f = conv.factor(hit[0])
            if f is None:
                problems.append(f"cambio {prices.currency}/{acc_cur} non disponibile")
                continue
            t.exec_price = hit[1] * f
            t.shares = t.amount / t.exec_price
        else:
            problems.append("prezzi non disponibili")
    if problems:
        out["error"] = (f"Impossibile calcolare le quote: {problems[0]}. Aggiorna i prezzi o inserisci "
                        "il prezzo unitario degli acquisti.")
        out["trades"] = [_trade_dict(t, acc_cur) for t in trades]
        return out

    # --- average cost accounting -------------------------------------------------
    shares = cost = realized = ZERO
    flows: list[tuple[date, Decimal]] = []  # money into the asset: buys +, sells -
    steps: list[tuple[date, Decimal, Decimal]] = []  # (day, shares after, cost after)
    for t in trades:
        if t.kind == "buy":
            shares += t.shares
            cost += t.amount
            flows.append((t.exec_date, t.amount))
        else:
            if t.shares > shares + TOLERANCE:
                out["error"] = (f"Vendita del {t.date.strftime('%d/%m/%Y')}: quote vendute ({_fmt_shares(t.shares)}) "
                                f"superiori a quelle possedute ({_fmt_shares(shares)}).")
                out["trades"] = [_trade_dict(x, acc_cur) for x in trades]
                return out
            sold_cost = cost if t.shares >= shares - TOLERANCE else cost * t.shares / shares
            t.realized = t.amount - sold_cost  # type: ignore[attr-defined]
            realized += t.amount - sold_cost
            cost -= sold_cost
            shares = max(shares - t.shares, ZERO) if t.shares < shares - TOLERANCE else ZERO
            flows.append((t.exec_date, -t.amount))
        steps.append((t.exec_date, shares, cost))

    if not prices:
        out["error"] = "Prezzi non disponibili: aggiorna i prezzi (serve la connessione)."
        out["trades"] = [_trade_dict(t, acc_cur) for t in trades]
        return out

    last_day, last_close = prices.last
    last_factor = conv.factor(last_day)
    if last_factor is None:
        out["error"] = f"Cambio {prices.currency}/{acc_cur} non disponibile."
        return out
    last_price = last_close * last_factor
    value = shares * last_price
    gain = value - cost

    # --- daily series from the first trade -----------------------------------------
    days: list[date] = []
    values: list[Decimal] = []
    invested: list[Decimal] = []
    si = 0
    cur_shares = cur_cost = ZERO
    d = first
    series_end = max(last_day, today)
    while d <= series_end:
        while si < len(steps) and steps[si][0] <= d:
            cur_shares, cur_cost = steps[si][1], steps[si][2]
            si += 1
        hit = prices.on_or_before(d)
        f = conv.factor(hit[0]) if hit else None
        if hit and f is not None:
            days.append(d)
            values.append(cur_shares * hit[1] * f)
            invested.append(cur_cost)
        d += timedelta(days=1)

    def value_on(day: date) -> Decimal:
        sh = ZERO
        for s_day, s_shares, _ in steps:
            if s_day <= day:
                sh = s_shares
        hit = prices.on_or_before(day)
        f = conv.factor(hit[0]) if hit else None
        return sh * hit[1] * f if hit and f is not None else ZERO

    # XIRR: buys are outflows, sells and the current value inflows
    held_days = (last_day - first).days
    irr = None
    if held_days >= MIN_DAYS_FOR_ANNUALIZED:
        irr = xirr([(d0, -float(a)) for d0, a in flows] + [(max(last_day, today), float(value))])

    # Last 12 months, Modified Dietz (flows weighted by the share of the year they were in)
    one_year_ago = series_end - timedelta(days=365)
    v0 = value_on(one_year_ago) if first <= one_year_ago else ZERO
    recent = [(d0, a) for d0, a in flows if d0 > one_year_ago]
    net_in = sum((a for _, a in recent), ZERO)
    weighted = sum((a * Decimal((series_end - d0).days) / 365 for d0, a in recent), ZERO)
    yoy_gain = value - v0 - net_in
    yoy_base = v0 + weighted
    yoy = None
    if first <= one_year_ago:
        yoy = {"gain": _num(yoy_gain), "pct": _pct(yoy_gain, yoy_base) if yoy_base > 0 else None}

    p1y = prices.on_or_before(last_day - timedelta(days=365))
    prev = prices.on_or_before(last_day - timedelta(days=1))
    idx = _downsample(days)

    out.update({
        "shares": _fmt_shares(shares),
        "invested": _num(cost),
        "value": _num(value),
        "gain": _num(gain),
        "return_pct": _pct(gain, cost) if cost > 0 else None,
        "realized": _num(realized),
        "annualized_pct": irr * 100 if irr is not None else None,
        "yoy": yoy,
        "instrument_12m_pct": float((last_close / p1y[1] - 1) * 100) if p1y else None,
        "day_change_pct": float((last_close / prev[1] - 1) * 100) if prev else 0.0,
        "last_price": str(last_close),
        "last_price_account": _num(last_price, 4),
        "last_date": last_day.isoformat(),
        "first_date": first.isoformat(),
        "held_days": held_days,
        "closed": shares <= TOLERANCE,
        "series": {
            "dates": [days[i].isoformat() for i in idx],
            "value": [round(float(values[i]), 2) for i in idx],
            "invested": [round(float(invested[i]), 2) for i in idx],
        },
        "trades": [_trade_dict(t, acc_cur) for t in trades],
        "_full": (days, values, invested),
        "_flows": flows,
        "_yoy": (v0 if first <= one_year_ago else ZERO, net_in, weighted, value),
    })
    return out


def _num(v: Decimal, places: int = 2) -> str:
    return money.fmt_decimal(v, places)


def _fmt_shares(v: Decimal | None) -> str | None:
    if v is None:
        return None
    q = v.quantize(Decimal(1).scaleb(-SHARES_PLACES))
    return format(q.normalize(), "f") if q else "0"


def _trade_dict(t: Trade, cur: str) -> dict:
    return {
        "id": t.id,
        "kind": t.kind,
        "date": t.date.isoformat(),
        "amount": money.fmt(t.amount_minor, cur),
        "shares": _fmt_shares(t.shares),
        "shares_input": _fmt_shares(t.shares_input),
        "price_input": format(t.price_input.normalize(), "f") if t.price_input else None,
        "exec_date": t.exec_date.isoformat() if t.exec_date else None,
        "exec_price": _num(t.exec_price, 4) if t.exec_price else None,
        "realized": _num(t.realized) if hasattr(t, "realized") else None,
        "fee": _num(t.fee) if t.fee is not None else None,
        "note": t.note,
        "transaction_id": t.transaction_id,
    }


# ===================================================================== accounts


def _investment_account(conn: sqlite3.Connection, account_id) -> sqlite3.Row:
    acc = accounts.account_row(conn, account_id)
    if acc["behavior"] != "investment":
        raise ValidationError("Gli asset si gestiscono solo nei conti di tipo investimenti.")
    return acc


def list_accounts(db: Database) -> list[dict]:
    """Investment accounts (tabs of the Investments view) with a light summary."""
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT a.id, a.name, a.currency, a.archived, a.bank FROM accounts a
               JOIN account_types t ON t.id = a.type_id WHERE t.behavior = 'investment'
               ORDER BY a.archived, a.name COLLATE NOCASE"""
        ).fetchall()
        bals = accounts.balances(conn)
        counts = dict(conn.execute("SELECT account_id, COUNT(*) FROM assets GROUP BY account_id").fetchall())
    return [{"id": r["id"], "name": r["name"], "bank": r["bank"], "currency": r["currency"],
             "archived": bool(r["archived"]), "liquidity": money.fmt(bals.get(r["id"], 0), r["currency"]),
             "asset_count": counts.get(r["id"], 0)} for r in rows]


def market_values(conn: sqlite3.Connection, today: date | None = None) -> dict[int, Decimal]:
    """account id -> current market value of its positions (account currency)."""
    out: dict[int, Decimal] = {}
    rows = conn.execute(
        "SELECT s.*, a.currency AS acc_cur FROM assets s JOIN accounts a ON a.id = s.account_id"
    ).fetchall()
    for asset in rows:
        res = compute_asset(conn, asset, asset["acc_cur"], today)
        if not res["error"]:
            out[asset["account_id"]] = out.get(asset["account_id"], ZERO) + Decimal(res["value"])
    return out


def value_series(conn: sqlite3.Connection, account_id: int, cur: str, today: date | None = None) -> dict[date, Decimal]:
    """Daily market value of the positions of an account (for the Home chart)."""
    total: dict[date, Decimal] = {}
    for asset in conn.execute("SELECT * FROM assets WHERE account_id = ?", (account_id,)).fetchall():
        res = compute_asset(conn, asset, cur, today)
        if res["error"]:
            continue
        days, values, _ = res["_full"]
        for d, v in zip(days, values):
            total[d] = total.get(d, ZERO) + v
    return total


def portfolio(db: Database, account_id: int, today: date | None = None) -> dict:
    """Everything the Investments tab of one account shows."""
    today = today or date.today()
    with db.connect() as conn:
        acc = _investment_account(conn, account_id)
        cur = acc["currency"]
        liquidity = accounts.balance(conn, account_id)
        assets = [compute_asset(conn, a, cur, today)
                  for a in conn.execute("SELECT * FROM assets WHERE account_id = ? ORDER BY name, ticker",
                                        (account_id,)).fetchall()]
        fetches = {r["symbol"]: dict(r) for r in conn.execute("SELECT * FROM market_fetch")}

    ok = [a for a in assets if not a["error"]]
    invested = sum((Decimal(a["invested"]) for a in ok), ZERO)
    value = sum((Decimal(a["value"]) for a in ok), ZERO)
    realized = sum((Decimal(a["realized"]) for a in ok), ZERO)
    gain = value - invested

    series = None
    if ok:
        all_days = sorted(set().union(*[set(a["_full"][0]) for a in ok]))
        tot_v: list[Decimal] = []
        tot_i: list[Decimal] = []
        per_asset: dict[int, tuple[list, list]] = {}
        for a in ok:
            days, vals, invs = a["_full"]
            m = dict(zip(days, zip(vals, invs)))
            av, ai = [], []
            last = None
            for d in all_days:
                if d in m:
                    last = m[d]
                av.append(last[0] if last else None)
                ai.append(last[1] if last else None)
            per_asset[a["id"]] = (av, ai)
        for i in range(len(all_days)):
            tot_v.append(sum((per_asset[a["id"]][0][i] or ZERO for a in ok), ZERO))
            tot_i.append(sum((per_asset[a["id"]][1][i] or ZERO for a in ok), ZERO))
        idx = _downsample(all_days)
        rnd = lambda x: None if x is None else round(float(x), 2)  # noqa: E731
        series = {
            "dates": [all_days[i].isoformat() for i in idx],
            "value": [rnd(tot_v[i]) for i in idx],
            "invested": [rnd(tot_i[i]) for i in idx],
            "assets": [{"id": a["id"], "value": [rnd(per_asset[a["id"]][0][i]) for i in idx],
                        "invested": [rnd(per_asset[a["id"]][1][i]) for i in idx]} for a in ok],
        }

    irr = None
    flows = [(d, a) for x in ok for d, a in x["_flows"]]
    if flows:
        last = max(date.fromisoformat(a["last_date"]) for a in ok)
        last = max(last, today)
        if (last - min(d for d, _ in flows)).days >= MIN_DAYS_FOR_ANNUALIZED:
            irr = xirr([(d, -float(a)) for d, a in flows] + [(last, float(value))])
    yoy_gain = yoy_pct = None
    if ok:
        earliest = min(date.fromisoformat(a["first_date"]) for a in ok)
        if (today - earliest).days >= 365:
            v0 = sum((a["_yoy"][0] for a in ok), ZERO)
            net_in = sum((a["_yoy"][1] for a in ok), ZERO)
            weighted = sum((a["_yoy"][2] for a in ok), ZERO)
            g = value - v0 - net_in
            base = v0 + weighted
            yoy_gain, yoy_pct = _num(g), (_pct(g, base) if base > 0 else None)

    for a in assets:
        a.pop("_full", None)
        a.pop("_flows", None)
        a.pop("_yoy", None)
        f = fetches.get(a["ticker"], {})
        a["price_error"] = f.get("error")
        a["fetched_on"] = f.get("fetched_on") or None

    return {
        "account": {"id": acc["id"], "name": acc["name"], "currency": cur, "archived": bool(acc["archived"]),
                    "bank": acc["bank"]},
        "summary": {
            "liquidity": money.fmt(liquidity, cur),
            "invested": _num(invested),
            "value": _num(value),
            "total": _num(value + money.from_minor(liquidity, cur)),
            "gain": _num(gain),
            "return_pct": _pct(gain, invested) if invested > 0 else None,
            "realized": _num(realized),
            "annualized_pct": irr * 100 if irr is not None else None,
            "yoy_gain": yoy_gain,
            "yoy_pct": yoy_pct,
            "asset_count": len(assets),
            "error_count": len(assets) - len(ok),
        },
        "series": series,
        "assets": assets,
    }


# ======================================================================== writes


def _clean_shares(value, field="quote") -> Decimal | None:
    if value in (None, ""):
        return None
    v = money.parse_decimal(value, field, max_places=SHARES_PLACES)
    if v <= 0:
        raise ValidationError(f"{field.capitalize()}: deve essere maggiore di zero.")
    return v


def _note(value) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > 200:
        raise ValidationError("Nota troppo lunga (max 200 caratteri).")
    return text


def _check_liquidity(conn: sqlite3.Connection, acc: sqlite3.Row, day: str) -> None:
    """A buy can't create money: the liquidity must stay >= 0 on its date and today."""
    cur = acc["currency"]
    for as_of in (day, None):
        bal = accounts.balance(conn, acc["id"], as_of)
        if bal < 0:  # the balance already includes the new buy
            when = "alla data dell'acquisto" if as_of else "oggi"
            raise ValidationError(
                f"Liquidità insufficiente su '{acc['name']}' {when} (mancano {money.fmt(-bal, cur)} {cur}). "
                "Registra prima un trasferimento o un'entrata sul conto."
            )


def _shares_held(conn: sqlite3.Connection, asset: sqlite3.Row, cur: str, day: date, exclude_trade: int | None) -> Decimal | None:
    """Shares held at the end of `day` (None if they can't be computed)."""
    res = compute_asset(conn, asset, cur)
    if res["error"] and not res["trades"]:
        return ZERO
    if res["error"]:
        return None
    held = ZERO
    for t in res["trades"]:
        if t["id"] == exclude_trade or date.fromisoformat(t["date"]) > day:
            continue
        sh = Decimal(t["shares"])
        held = held + sh if t["kind"] == "buy" else held - sh
    return held


def _write_trade(conn: sqlite3.Connection, asset: sqlite3.Row, acc: sqlite3.Row, data: dict,
                 current: sqlite3.Row | None) -> int:
    kind = current["kind"] if current else data.get("kind", "buy")
    if kind not in ("buy", "sell"):
        raise ValidationError("Tipo di operazione non valido.")
    cur = acc["currency"]
    day = transactions._date(data.get("date"))
    if acc["archived"]:
        raise ValidationError(f"Il conto '{acc['name']}' è archiviato.")
    if day < acc["opened_on"]:
        raise ValidationError(f"Il conto è stato aperto il {transactions._it(acc['opened_on'])}: data non valida.")
    amount = money.parse_amount(data.get("amount"), cur, "importo" if kind == "buy" else "importo incassato")
    note = _note(data.get("note"))
    price = shares = None
    if kind == "buy":
        price = _clean_shares(data.get("price"), "prezzo unitario")
        shares = _clean_shares(data.get("shares"))
        if price and shares:
            raise ValidationError("Inserisci il prezzo unitario oppure il numero di quote, non entrambi.")
    else:
        if str(data.get("shares", "")).strip().lower() in ("all", "tutte"):
            held = _shares_held(conn, asset, cur, date.fromisoformat(day), current["id"] if current else None)
            if held is None:
                raise ValidationError("Quote possedute non calcolabili (prezzi mancanti): inserisci il numero di quote.")
            if held <= 0:
                raise ValidationError("Non ci sono quote da vendere a quella data.")
            shares = held
        else:
            shares = _clean_shares(data.get("shares"))
            if shares is None:
                raise ValidationError("Inserisci il numero di quote vendute.")
    fee = None
    if data.get("fee") not in (None, ""):
        fee = money.parse_amount(data.get("fee"), cur, "commissione")

    label = f"{'Acquisto' if kind == 'buy' else 'Vendita'} {asset['ticker']}" + (f" · {note}" if note else "")
    side = "from" if kind == "buy" else "to"
    tx_row = {"kind": kind, "date": day, f"{side}_account_id": acc["id"], f"{side}_amount": amount,
              "description": label[:transactions.MAX_DESCRIPTION], "auto": 1}
    tx_id = transactions.write(conn, tx_row, current["transaction_id"] if current else None)

    fee_id = current["fee_transaction_id"] if current else None
    if fee is not None:
        fee_row = {"kind": "fee", "date": day, "from_account_id": acc["id"], "from_amount": fee,
                   "category_id": categories.system_category(conn, "fees"),
                   "description": f"Commissione: {label}"[:transactions.MAX_DESCRIPTION], "linked_id": tx_id, "auto": 1}
        fee_id = transactions.write(conn, fee_row, fee_id)
    elif fee_id is not None:
        conn.execute("UPDATE asset_trades SET fee_transaction_id = NULL WHERE fee_transaction_id = ?", (fee_id,))
        conn.execute("DELETE FROM transactions WHERE id = ?", (fee_id,))
        fee_id = None

    now = now_iso()
    values = {"kind": kind, "date": day, "amount": amount, "shares": _plain(shares), "price": _plain(price),
              "note": note, "transaction_id": tx_id, "fee_transaction_id": fee_id, "updated_at": now}
    if current is None:
        values.update(asset_id=asset["id"], created_at=now)
        cols = ", ".join(values)
        trade_id = conn.execute(f"INSERT INTO asset_trades ({cols}) VALUES ({', '.join('?' * len(values))})",
                                tuple(values.values())).lastrowid
    else:
        sets = ", ".join(f"{k} = ?" for k in values)
        conn.execute(f"UPDATE asset_trades SET {sets} WHERE id = ?", (*values.values(), current["id"]))
        trade_id = current["id"]

    if kind == "buy" or fee is not None:
        _check_liquidity(conn, acc, day)
    # sells (and edits) must never leave more shares sold than held
    res = compute_asset(conn, asset, cur)
    if res["error"] and "superiori" in res["error"]:
        raise ValidationError(res["error"])
    return trade_id


def _plain(v: Decimal | None) -> str | None:
    return format(v.normalize(), "f") if v is not None else None


def search(provider: market.Provider, query: str) -> list[dict]:
    query = str(query or "").strip()
    if len(query) > 60:
        raise ValidationError("Ricerca troppo lunga.")
    try:
        found = provider.search(query)
    except market.MarketError as e:
        raise ValidationError(str(e)) from None
    return [{"symbol": c.symbol, "name": c.name, "exchange": c.exchange, "type": c.kind} for c in found]


def create_asset(db: Database, provider: market.Provider, account_id: int, data: dict) -> dict:
    """New asset with its first buy. The ticker is checked on Yahoo unless offline, in
    which case the quote currency must be given."""
    try:
        ticker = market.check_symbol(data.get("ticker"))
    except market.MarketError as e:
        raise ValidationError(str(e)) from None
    try:
        meta = provider.meta(ticker)
    except market.MarketError as e:
        currency = str(data.get("currency") or "").strip()
        if not currency:
            raise ValidationError(f"{e} Indica la valuta dello strumento per aggiungerlo comunque.") from None
        money.check_currency(market.normalize_currency(currency)[0])
        meta = market.Meta(ticker, str(data.get("name") or ticker), "", currency)
    with db.transaction() as conn:
        acc = _investment_account(conn, account_id)
        if acc["archived"]:
            raise ValidationError("Il conto è archiviato.")
        name = " ".join(str(data.get("name") or meta.name or ticker).split())[:120]
        try:
            asset_id = conn.execute(
                "INSERT INTO assets (account_id, ticker, name, exchange, currency, input_symbol, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (acc["id"], ticker, name, meta.exchange, meta.currency, str(data.get("input_symbol") or ticker)[:40],
                 now_iso()),
            ).lastrowid
        except sqlite3.IntegrityError:
            raise ConflictError(f"{ticker} è già presente in questo conto: aggiungi un acquisto all'asset.") from None
        asset = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        _write_trade(conn, asset, acc, {**data, "kind": "buy"}, None)
    return {"id": asset_id, "ticker": ticker, "name": name}


def _asset(conn: sqlite3.Connection, asset_id: int) -> tuple[sqlite3.Row, sqlite3.Row]:
    asset = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
    if not asset:
        raise NotFoundError("Asset non trovato.")
    return asset, accounts.account_row(conn, asset["account_id"])


def update_asset(db: Database, provider: market.Provider, asset_id: int, data: dict) -> dict:
    with db.transaction() as conn:
        asset, _ = _asset(conn, asset_id)
        fields: dict = {}
        if "name" in data:
            name = " ".join(str(data["name"] or "").split())
            if not name:
                raise ValidationError("Il nome è obbligatorio.")
            fields["name"] = name[:120]
        if data.get("ticker") and str(data["ticker"]).strip().upper() != asset["ticker"]:
            try:
                ticker = market.check_symbol(data["ticker"])
                meta = provider.meta(ticker)
            except market.MarketError as e:
                raise ValidationError(str(e)) from None
            fields.update(ticker=ticker, exchange=meta.exchange, currency=meta.currency)
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            try:
                conn.execute(f"UPDATE assets SET {sets} WHERE id = ?", (*fields.values(), asset_id))
            except sqlite3.IntegrityError:
                raise ConflictError("Questo ticker è già presente nel conto.") from None
            if "ticker" in fields:
                label_old, label_new = asset["ticker"], fields["ticker"]
                conn.execute(
                    "UPDATE transactions SET description = REPLACE(description, ?, ?) WHERE id IN"
                    " (SELECT transaction_id FROM asset_trades WHERE asset_id = ?"
                    "  UNION SELECT fee_transaction_id FROM asset_trades WHERE asset_id = ?)",
                    (label_old, label_new, asset_id, asset_id),
                )
    return {"id": asset_id, **fields}


def delete_asset(db: Database, asset_id: int) -> None:
    """Remove an asset with all its buys and sells (and their operations)."""
    with db.transaction() as conn:
        _asset(conn, asset_id)
        ids = conn.execute(
            "SELECT transaction_id, fee_transaction_id FROM asset_trades WHERE asset_id = ?", (asset_id,)
        ).fetchall()
        conn.execute("DELETE FROM asset_trades WHERE asset_id = ?", (asset_id,))
        for tx_id, fee_id in ids:
            for i in (fee_id, tx_id):
                if i is not None:
                    conn.execute("DELETE FROM transactions WHERE id = ?", (i,))
        conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,))


def add_trade(db: Database, asset_id: int, data: dict) -> dict:
    with db.transaction() as conn:
        asset, acc = _asset(conn, asset_id)
        trade_id = _write_trade(conn, asset, acc, data, None)
    return {"id": trade_id}


def update_trade(db: Database, trade_id: int, data: dict) -> dict:
    with db.transaction() as conn:
        current = conn.execute("SELECT * FROM asset_trades WHERE id = ?", (trade_id,)).fetchone()
        if not current:
            raise NotFoundError("Operazione non trovata.")
        asset, acc = _asset(conn, current["asset_id"])
        _write_trade(conn, asset, acc, data, current)
    return {"id": trade_id}


def delete_trade(db: Database, trade_id: int) -> None:
    with db.transaction() as conn:
        current = conn.execute("SELECT * FROM asset_trades WHERE id = ?", (trade_id,)).fetchone()
        if not current:
            raise NotFoundError("Operazione non trovata.")
        asset, acc = _asset(conn, current["asset_id"])
        n = conn.execute("SELECT COUNT(*) FROM asset_trades WHERE asset_id = ?", (asset["id"],)).fetchone()[0]
        if n == 1:
            raise ConflictError("È l'unica operazione dell'asset: elimina l'asset.")
        conn.execute("DELETE FROM asset_trades WHERE id = ?", (trade_id,))
        for i in (current["fee_transaction_id"], current["transaction_id"]):
            if i is not None:
                conn.execute("DELETE FROM transactions WHERE id = ?", (i,))
        res = compute_asset(conn, asset, acc["currency"])
        if res["error"] and "superiori" in res["error"]:
            raise ValidationError(f"Non eliminabile: {res['error']}")
        if current["kind"] == "sell" and accounts.balance(conn, acc["id"]) < 0:
            raise ValidationError("Eliminando la vendita la liquidità del conto diventerebbe negativa.")

