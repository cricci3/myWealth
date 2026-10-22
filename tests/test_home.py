from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from mywealth import accounts, fx, home, investments as inv, transactions as tx

from .helpers import cat, make_account
from .test_investments import PROVIDER

TODAY = date.today()


def test_summary_totals(db):
    eur = make_account(db, "Corrente", "EUR", "1000", opened=(TODAY - timedelta(days=10)).isoformat())
    chf = make_account(db, "Svizzero", "CHF", "100", opened=(TODAY - timedelta(days=10)).isoformat())
    make_account(db, "Dollari", "USD", "50", opened=(TODAY - timedelta(days=10)).isoformat())
    with db.transaction() as conn:
        fx.store_rates(conn, "CHF", [(TODAY - timedelta(days=5), Decimal("1.1"))], "yahoo")
    s = home.summary(db)
    assert s["total_eur"] == "1110.00"
    assert s["missing_rates"] == ["USD"]
    assert s["by_currency"][0] == {"currency": "EUR", "value": "1000.00"}
    card = next(c for c in s["accounts"] if c["id"] == chf["id"])
    assert (card["value"], card["eur"], card["rate"]) == ("100.00", "110.00", "1.1")
    assert next(c for c in s["accounts"] if c["name"] == "Dollari")["eur"] is None
    accounts.update_account(db, eur["id"], {"archived": True})
    s = home.summary(db)
    assert all(c["id"] != eur["id"] for c in s["accounts"])
    assert s["total_eur"] == "1110.00"  # an archived account with money still counts


def test_summary_investment_account_includes_positions(db):
    broker = make_account(db, "Broker", "EUR", "1500", opened=(TODAY - timedelta(days=410)).isoformat(),
                          behavior="investment")
    inv.create_asset(db, PROVIDER, broker["id"], {"ticker": "ETF.MI", "amount": "1000",
                                                  "date": (TODAY - timedelta(days=400)).isoformat()})
    inv.refresh_prices(db, PROVIDER)
    card = home.summary(db)["accounts"][0]
    assert (card["cash"], card["positions"], card["value"]) == ("500.00", "1200.00", "1700.00")


def test_history(db):
    start = TODAY - timedelta(days=20)
    eur = make_account(db, "Corrente", "EUR", "100", opened=start.isoformat())
    chf = make_account(db, "Svizzero", "CHF", "100", opened=(TODAY - timedelta(days=5)).isoformat())
    with db.transaction() as conn:
        fx.store_rates(conn, "CHF", [(start, Decimal("2"))], "yahoo")
    tx.create(db, {"kind": "expense", "account_id": eur["id"], "amount": "40", "date": (TODAY - timedelta(days=2)).isoformat(),
                   "category_id": cat(db, "Svago")})
    h = home.history(db, "max")
    assert h["dates"][0] == start.isoformat() and h["dates"][-1] == TODAY.isoformat()
    assert h["total"][0] == 100.0 and h["total"][-1] == 260.0  # 60 EUR + 100 CHF × 2
    line = next(a for a in h["accounts"] if a["id"] == chf["id"])
    assert line["value"][0] is None and line["value"][-1] == 200.0
    assert home.history(db, "30")["dates"][0] == start.isoformat()  # never before the first opening
    assert len(home.history(db, "bogus")["dates"]) == 21


def test_history_with_investments(db):
    broker = make_account(db, "Broker", "EUR", "1000", opened=(TODAY - timedelta(days=410)).isoformat(),
                          behavior="investment")
    inv.create_asset(db, PROVIDER, broker["id"], {"ticker": "ETF.MI", "amount": "1000",
                                                  "date": (TODAY - timedelta(days=400)).isoformat()})
    inv.refresh_prices(db, PROVIDER)
    h = home.history(db, "30")
    assert h["total"][-1] == 1200.0 and h["total"][0] == 1100.0  # 100 shares × 11 (last close before)


def test_home_api(server, db):
    _, client = server
    make_account(db, "Corrente", "EUR", "10")
    assert client.json("GET", "/api/home")[1]["total_eur"] == "10.00"
    assert client.json("GET", "/api/home/history?range=30")[1]["range"] == "30"
    assert client.json("GET", "/api/home/history")[1]["range"] == "90"
