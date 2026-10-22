"""Market data providers (Yahoo Finance) — the app's only outbound traffic.

Yahoo only ever receives tickers / currency pairs (e.g. `CHFEUR=X`, `VWCE.DE`) and a
history start date. Amounts, account names and anything else about the user's money
never leave the computer.

`DemoProvider` returns deterministic synthetic data and makes no network call at all.
Ported and adapted from PortfolioTracker (market.py / core.py, MIT, same author).
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

log = logging.getLogger(__name__)

ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
SYMBOL_RE = re.compile(r"^[A-Z0-9.\-=^]{1,24}$")
# Currencies Yahoo quotes in minor units ("pence"): (real currency, divisor)
MINOR_UNITS = {"GBp": ("GBP", 100), "GBX": ("GBP", 100), "ZAc": ("ZAR", 100), "ILA": ("ILS", 100)}


class MarketError(Exception):
    """Yahoo can't be reached or has no data. The message is shown to the user."""


class OfflineError(MarketError):
    pass


@dataclass
class Candidate:
    symbol: str
    name: str
    exchange: str
    kind: str = ""


@dataclass
class Meta:
    ticker: str
    name: str
    exchange: str
    currency: str


def is_isin(value: str) -> bool:
    return bool(ISIN_RE.match(value.strip().upper()))


def check_symbol(value: str) -> str:
    symbol = str(value or "").strip().upper()
    if not SYMBOL_RE.match(symbol):
        raise MarketError(f"Simbolo non valido: '{value}'.")
    return symbol


def fx_symbol(currency: str) -> str:
    return f"{currency}EUR=X"


def normalize_currency(currency: str) -> tuple[str, int]:
    """Yahoo quote currency -> (ISO currency, divisor), e.g. GBp -> (GBP, 100)."""
    if currency in MINOR_UNITS:
        return MINOR_UNITS[currency]
    return (currency or "").upper(), 1


class Provider:
    name = "base"
    network = True

    def history(self, symbol: str, start: date) -> list[tuple[date, Decimal]]:
        """Daily closes from `start` to today, oldest first."""
        raise NotImplementedError

    def search(self, query: str) -> list[Candidate]:
        raise NotImplementedError

    def meta(self, ticker: str) -> Meta:
        raise NotImplementedError


class YahooProvider(Provider):
    name = "yahoo"

    def history(self, symbol: str, start: date) -> list[tuple[date, Decimal]]:
        import yfinance as yf

        symbol = check_symbol(symbol)
        try:
            hist = yf.Ticker(symbol).history(start=start, end=date.today() + timedelta(days=1), auto_adjust=False)
        except Exception as e:  # yfinance raises many different things on network trouble
            raise MarketError(f"Impossibile scaricare i dati di {symbol} da Yahoo Finance: {e}") from e
        if hist is None or hist.empty or "Close" not in hist:
            raise MarketError(f"Nessun dato su Yahoo Finance per '{symbol}' dal {start.isoformat()}.")
        out: dict[date, Decimal] = {}
        for ts, value in hist["Close"].dropna().items():
            if value is None or not math.isfinite(float(value)) or float(value) <= 0:
                continue
            out[ts.date()] = Decimal(repr(float(value)))
        if not out:
            raise MarketError(f"Nessun dato su Yahoo Finance per '{symbol}'.")
        return sorted(out.items())

    def search(self, query: str) -> list[Candidate]:
        import yfinance as yf

        query = query.strip()
        if not query:
            return []
        try:
            quotes = yf.Search(query, max_results=10, news_count=0).quotes or []
        except Exception as e:
            raise MarketError(f"Impossibile cercare su Yahoo Finance: {e}") from e
        return [
            Candidate(q.get("symbol", ""), q.get("shortname") or q.get("longname") or "", q.get("exchange", ""),
                      q.get("quoteType", ""))
            for q in quotes
            if q.get("symbol")
        ]

    def meta(self, ticker: str) -> Meta:
        import yfinance as yf

        ticker = check_symbol(ticker)
        tk = yf.Ticker(ticker)
        currency = exchange = name = ""
        try:
            fi = tk.fast_info
            currency = getattr(fi, "currency", "") or ""
            exchange = getattr(fi, "exchange", "") or ""
        except Exception:
            pass
        try:
            info = tk.info or {}
            name = info.get("longName") or info.get("shortName") or ""
            currency = currency or info.get("currency", "")
            exchange = exchange or info.get("exchange", "")
        except Exception:
            pass
        if not currency:
            raise MarketError(f"Ticker '{ticker}' non trovato su Yahoo Finance.")
        return Meta(ticker, name or ticker, exchange, currency)


class OfflineProvider(Provider):
    """Used when the user turns on offline mode."""

    name = "offline"
    network = False

    def history(self, symbol, start):
        raise OfflineError("Modalità offline: nessuna connessione a Yahoo Finance.")

    def search(self, query):
        raise OfflineError("Modalità offline: la ricerca su Yahoo Finance non è disponibile.")

    def meta(self, ticker):
        raise OfflineError("Modalità offline: impossibile verificare il ticker su Yahoo Finance.")


# ---------------------------------------------------------------------- demo

# EUR per unit, roughly realistic levels for the synthetic FX series
DEMO_FX = {"CHF": 1.06, "USD": 0.92, "GBP": 1.17, "JPY": 0.0062, "SEK": 0.087, "NOK": 0.086, "DKK": 0.134,
           "PLN": 0.23, "CZK": 0.04, "CAD": 0.68, "AUD": 0.61}

DEMO_ASSETS = {
    "VWCE.DE": ("Vanguard FTSE All-World UCITS ETF Acc", "GER", "EUR", 98.0),
    "SWDA.MI": ("iShares Core MSCI World UCITS ETF", "MIL", "EUR", 85.0),
    "EIMI.MI": ("iShares Core MSCI EM IMI UCITS ETF", "MIL", "EUR", 30.0),
    "ENEL.MI": ("Enel S.p.A.", "MIL", "EUR", 6.5),
    "AAPL": ("Apple Inc.", "NMS", "USD", 180.0),
    "MSFT": ("Microsoft Corporation", "NMS", "USD", 400.0),
    "VOO": ("Vanguard S&P 500 ETF", "PCX", "USD", 450.0),
    "IE00BK5BQT80": ("Vanguard FTSE All-World UCITS ETF Acc", "GER", "EUR", 98.0),
}


def _seed(symbol: str) -> int:
    return int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)


def demo_series(symbol: str, start: date, end: date, level: float, vol_scale: float = 1.0) -> list[tuple[date, Decimal]]:
    """Deterministic random walk on business days, scaled so that the last price is
    `level`. The path is anchored to a fixed epoch, so asking from a different start
    returns the same values."""
    seed = _seed(symbol)
    epoch = date(2015, 1, 1)
    state = seed
    drift = ((seed % 9) + 3) / 100 / 252 * vol_scale  # +3% to +11% a year
    vol = (0.006 + (seed % 7) / 1000) * vol_scale
    price = level
    path = []
    d = epoch
    i = 0
    while d <= end:
        if d.weekday() < 5:
            state = (1103515245 * state + 12345) % (2**31)
            shock = (state / 2**31 - 0.5) * 2 * vol * math.sqrt(3)
            cycle = 0.0015 * vol_scale * math.sin(i / (40 + seed % 30))
            price *= 1 + drift + shock + cycle
            # keep FX near its level: mean reversion
            if vol_scale < 1:
                price += (level - price) * 0.02
            i += 1
            path.append((d, price))
        d += timedelta(days=1)
    scale = level / path[-1][1] if path else 1
    return [(d, Decimal(f"{p * scale:.6g}")) for d, p in path if d >= start]


class DemoProvider(Provider):
    name = "demo"
    network = False

    def history(self, symbol, start):
        symbol = check_symbol(symbol)
        today = date.today()
        if symbol.endswith("EUR=X"):
            level = DEMO_FX.get(symbol[:3], 1.0)
            return demo_series(symbol, start, today, level, vol_scale=0.35)
        level = DEMO_ASSETS.get(symbol, ("", "", "", 20 + _seed(symbol) % 180))[3]
        return demo_series(symbol, start, today, level)

    def search(self, query):
        q = query.strip().upper()
        if not q:
            return []
        found = [Candidate(t, m[0], m[1], "ETF" if "ETF" in m[0] else "EQUITY")
                 for t, m in DEMO_ASSETS.items() if q in t or q in m[0].upper()]
        return found or [Candidate(q, f"Demo {q}", "DEMO", "EQUITY")]

    def meta(self, ticker):
        ticker = check_symbol(ticker)
        name, exch, cur, _ = DEMO_ASSETS.get(ticker, (f"Demo {ticker}", "DEMO", "EUR", 0))
        return Meta(ticker, name, exch, cur)
