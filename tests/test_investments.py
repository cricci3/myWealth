from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from mywealth import accounts, fx, investments as inv, market, transactions as tx
from mywealth.errors import ConflictError, NotFoundError, ValidationError

from .helpers import balance, make_account

TODAY = date.today()
D0 = TODAY - timedelta(days=400)
D1 = TODAY - timedelta(days=200)


class Provider(market.Provider):
    name = "yahoo"

    def __init__(self, prices=None, metas=None, fail=False):
        self.prices = prices or {}
        self.metas = metas or {}
        self.fail = fail

    def history(self, symbol, start):
        if self.fail:
            raise market.MarketError("offline")
        return [(d, Decimal(p)) for d, p in sorted(self.prices.get(symbol, {}).items()) if d >= start]

    def meta(self, ticker):
        if self.fail or ticker not in self.metas:
            raise market.MarketError(f"Ticker '{ticker}' non trovato.")
        return market.Meta(ticker, *self.metas[ticker])

    def search(self, query):
        return [market.Candidate(t, m[0], m[1]) for t, m in self.metas.items() if query.upper() in t]


PROVIDER = Provider(
    prices={
        "ETF.MI": {D0: "10", D1: "11", TODAY: "12"},
        "AAPL": {D0: "100", TODAY: "120"},
        "VOD.L": {D0: "1000", TODAY: "1100"},  # pence
    },
    metas={"ETF.MI": ("Demo ETF", "MIL", "EUR"), "AAPL": ("Apple", "NMS", "USD"), "VOD.L": ("Vodafone", "LSE", "GBp")},
)


@pytest.fixture
def broker(db):
    return make_account(db, "Broker", "EUR", "1000", opened=(D0 - timedelta(days=5)).isoformat(), behavior="investment")


def add(db, acc, ticker="ETF.MI", amount="1000", day=D0, **kw):
    asset = inv.create_asset(db, PROVIDER, acc["id"], {"ticker": ticker, "amount": amount, "date": day.isoformat(), **kw})
    inv.refresh_prices(db, PROVIDER)
    return asset


def pf(db, acc):
    return inv.portfolio(db, acc["id"])


def asset_of(db, acc, ticker="ETF.MI"):
    return next(a for a in pf(db, acc)["assets"] if a["ticker"] == ticker)


def test_buy_moves_liquidity_into_the_position(db, broker):
    add(db, broker)
    p = pf(db, broker)
    a = p["assets"][0]
    assert a["error"] is None
    assert (a["shares"], a["invested"], a["value"], a["gain"]) == ("100", "1000.00", "1200.00", "200.00")
    assert a["return_pct"] == pytest.approx(20.0)
    assert p["summary"]["liquidity"] == "0.00"
    assert p["summary"]["total"] == "1200.00"
    assert balance(db, broker["id"]) == "0.00"
    buy = tx.list_transactions(db, {"kind": "buy"})["items"][0]
    assert buy["description"] == "Acquisto ETF.MI" and not buy["editable"]
    with pytest.raises(ConflictError):
        tx.delete(db, buy["id"])


def test_buy_blocked_without_liquidity(db, broker):
    with pytest.raises(ValidationError, match="Liquidità insufficiente"):
        add(db, broker, amount="1000,01")
    assert inv.portfolio(db, broker["id"])["assets"] == []  # nothing half-saved
    add(db, broker, amount="600")
    asset_id = asset_of(db, broker)["id"]
    with pytest.raises(ValidationError, match="Liquidità"):
        inv.add_trade(db, asset_id, {"kind": "buy", "amount": "500", "date": D1.isoformat()})
    # liquidity must exist on the buy date too, not only today
    other = make_account(db, "Corrente", "EUR", "5000", opened="2020-01-01")
    tx.create(db, {"kind": "transfer", "from_account_id": other["id"], "to_account_id": broker["id"],
                   "amount": "1000", "date": TODAY.isoformat()})
    with pytest.raises(ValidationError, match="alla data"):
        inv.add_trade(db, asset_id, {"kind": "buy", "amount": "500", "date": D1.isoformat()})
    inv.add_trade(db, asset_id, {"kind": "buy", "amount": "500", "date": TODAY.isoformat()})


def test_price_or_shares_given_by_the_user(db, broker):
    add(db, broker, amount="500", price="12,5")  # 40 shares instead of 50 at the market close
    assert asset_of(db, broker)["shares"] == "40"
    inv.add_trade(db, asset_of(db, broker)["id"], {"kind": "buy", "amount": "300", "date": D1.isoformat(), "shares": "25"})
    a = asset_of(db, broker)
    assert a["shares"] == "65" and a["invested"] == "800.00"
    with pytest.raises(ValidationError):
        inv.add_trade(db, a["id"], {"kind": "buy", "amount": "1", "date": D1.isoformat(), "shares": "1", "price": "1"})


def test_sell_at_average_cost(db, broker):
    add(db, broker)  # 100 shares, cost 1000
    a = asset_of(db, broker)
    inv.add_trade(db, a["id"], {"kind": "sell", "amount": "550", "date": D1.isoformat(), "shares": "50"})
    a = asset_of(db, broker)
    assert (a["shares"], a["invested"], a["realized"], a["value"]) == ("50", "500.00", "50.00", "600.00")
    assert balance(db, broker["id"]) == "550.00"
    sell = next(t for t in a["trades"] if t["kind"] == "sell")
    assert sell["realized"] == "50.00"
    with pytest.raises(ValidationError, match="superiori"):
        inv.add_trade(db, a["id"], {"kind": "sell", "amount": "1", "date": TODAY.isoformat(), "shares": "50,0001"})
    inv.add_trade(db, a["id"], {"kind": "sell", "amount": "600", "date": TODAY.isoformat(), "shares": "tutte"})
    a = asset_of(db, broker)
    assert (a["shares"], a["invested"], a["value"], a["closed"]) == ("0", "0.00", "0.00", True)
    assert a["realized"] == "150.00"
    assert balance(db, broker["id"]) == "1150.00"


def test_sell_requires_shares_and_cannot_predate_buys(db, broker):
    add(db, broker, day=D1)
    a = asset_of(db, broker)
    with pytest.raises(ValidationError, match="quote"):
        inv.add_trade(db, a["id"], {"kind": "sell", "amount": "10", "date": TODAY.isoformat()})
    with pytest.raises(ValidationError):
        inv.add_trade(db, a["id"], {"kind": "sell", "amount": "10", "date": D0.isoformat(), "shares": "1"})


def test_fees_are_expenses_outside_returns(db, broker):
    add(db, broker, amount="990", fee="10")
    a = asset_of(db, broker)
    assert a["invested"] == "990.00"
    assert balance(db, broker["id"]) == "0.00"
    fee = tx.list_transactions(db, {"kind": "fee"})["items"][0]
    assert fee["category_name"] == "Commissioni bancarie" and fee["amount"] == "10.00"
    trade = a["trades"][0]
    inv.update_trade(db, trade["id"], {"amount": "990", "date": D0.isoformat()})  # fee removed
    assert tx.list_transactions(db, {"kind": "fee"})["total"] == 0
    assert balance(db, broker["id"]) == "10.00"


def test_edit_and_delete_trades_and_asset(db, broker):
    add(db, broker, amount="500")
    a = asset_of(db, broker)
    with pytest.raises(ConflictError):
        inv.delete_trade(db, a["trades"][0]["id"])
    inv.add_trade(db, a["id"], {"kind": "buy", "amount": "200", "date": D1.isoformat()})
    a = asset_of(db, broker)
    inv.update_trade(db, a["trades"][1]["id"], {"amount": "300", "date": D1.isoformat(), "note": "PAC"})
    a = asset_of(db, broker)
    assert a["invested"] == "800.00" and a["trades"][1]["note"] == "PAC"
    assert "PAC" in tx.get(db, a["trades"][1]["transaction_id"])["description"]
    inv.delete_trade(db, a["trades"][1]["id"])
    assert balance(db, broker["id"]) == "500.00"
    inv.delete_asset(db, a["id"])
    assert balance(db, broker["id"]) == "1000.00"
    assert tx.list_transactions(db)["total"] == 0
    with pytest.raises(NotFoundError):
        inv.delete_asset(db, a["id"])


def test_foreign_currency_asset(db, broker):
    with db.transaction() as conn:
        fx.store_rates(conn, "USD", [(D0, Decimal("0.9")), (TODAY, Decimal("0.8"))], "yahoo")
        fx.store_rates(conn, "GBP", [(D0, Decimal("1.2"))], "yahoo")
    add(db, broker, "AAPL", "900")  # 100 USD × 0.9 = 90 EUR per share -> 10 shares
    a = asset_of(db, broker, "AAPL")
    assert a["currency"] == "USD" and a["shares"] == "10"
    assert a["value"] == "960.00"  # 10 × 120 USD × 0.8
    # quoted in pence: 1000 GBp = 10 GBP = 12 EUR
    broker2 = make_account(db, "Broker 2", "EUR", "120", opened=D0.isoformat(), behavior="investment")
    add(db, broker2, "VOD.L", "120")
    v = asset_of(db, broker2, "VOD.L")
    assert v["currency"] == "GBP" and v["shares"] == "10" and v["value"] == "132.00"


def test_asset_in_usd_account(db):
    with db.transaction() as conn:
        fx.store_rates(conn, "USD", [(D0, Decimal("0.9"))], "yahoo")
    us = make_account(db, "Broker USA", "USD", "1000", opened=D0.isoformat(), behavior="investment")
    add(db, us, "AAPL", "1000")
    a = asset_of(db, us, "AAPL")
    assert (a["shares"], a["value"]) == ("10", "1200.00")
    with db.connect() as conn:
        assert inv.market_values(conn)[us["id"]] == Decimal("1200.00")


def test_missing_prices_reported_per_asset(db, broker):
    inv.create_asset(db, Provider(fail=True), broker["id"],
                     {"ticker": "NEW.MI", "currency": "EUR", "amount": "100", "date": D1.isoformat()})
    a = asset_of(db, broker, "NEW.MI")
    assert "prezzi" in a["error"]
    with pytest.raises(ValidationError, match="valuta"):
        inv.create_asset(db, Provider(fail=True), broker["id"], {"ticker": "X", "amount": "1", "date": D1.isoformat()})


def test_validation(db, broker):
    std = make_account(db, "Corrente", "EUR", "100")
    with pytest.raises(ValidationError, match="investimenti"):
        add(db, std)
    with pytest.raises(ValidationError):
        add(db, broker, ticker="NOPE")
    with pytest.raises(ValidationError):
        add(db, broker, ticker="bad ticker!")
    add(db, broker, amount="10")
    with pytest.raises(ConflictError):
        add(db, broker, amount="10")
    with pytest.raises(ConflictError):
        accounts.delete_account(db, broker["id"])


def test_returns_and_series(db, broker):
    add(db, broker)
    p = pf(db, broker)
    a = p["assets"][0]
    # held ~400 days: 1000 -> 1200
    assert a["annualized_pct"] == pytest.approx(18.1, abs=0.3)
    assert a["yoy"] is not None and p["summary"]["yoy_pct"] is not None
    s = p["series"]
    assert s["dates"][0] == D0.isoformat() and s["dates"][-1] == TODAY.isoformat()
    assert s["value"][0] == 1000.0 and s["value"][-1] == 1200.0 and s["invested"][-1] == 1000.0
    assert len(s["dates"]) <= inv.MAX_POINTS + 1


def test_xirr():
    d0 = date(2024, 1, 1)
    assert inv.xirr([(d0, -1000.0), (date(2025, 1, 1), 1100.0)]) == pytest.approx(0.0998, abs=1e-3)
    assert inv.xirr([(d0, -1000.0)]) is None


def test_refresh_prices_once_a_day(db, broker):
    add(db, broker)
    calls = []

    class Counting(Provider):
        def history(self, symbol, start):
            calls.append(symbol)
            return super().history(symbol, start)

    p = Counting(PROVIDER.prices)
    inv.refresh_prices(db, p)
    assert calls == []  # already downloaded today by add()
    inv.refresh_prices(db, p, force=True)
    assert calls == ["ETF.MI"]


def test_investments_api(server, db):
    _, client = server
    acc = make_account(db, "Broker", "EUR", "5000", opened=D0.isoformat(), behavior="investment")
    assert client.json("GET", "/api/market/search?q=VWCE")[1][0]["symbol"] == "VWCE.DE"  # demo provider
    status, asset = client.json("POST", f"/api/investments/{acc['id']}/assets",
                                {"ticker": "VWCE.DE", "amount": "1.000", "date": D1.isoformat()})
    assert status == 200
    status, data = client.json("GET", f"/api/investments/{acc['id']}")
    assert status == 200 and data["assets"][0]["error"] is None and data["summary"]["liquidity"] == "4000.00"
    assert client.json("POST", f"/api/assets/{asset['id']}/trades",
                       {"kind": "sell", "amount": "100", "shares": "1", "date": TODAY.isoformat()})[0] == 200
    assert client.json("GET", "/api/investments")[1][0]["asset_count"] == 1
    assert client.json("POST", "/api/investments/refresh")[0] == 200
    assert client.json("PUT", f"/api/assets/{asset['id']}", {"name": "All-World"})[0] == 200
    assert client.json("DELETE", f"/api/assets/{asset['id']}")[0] == 200
