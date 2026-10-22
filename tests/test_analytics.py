from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from mywealth import analytics, fx, investments as inv, transactions as tx
from mywealth.errors import ValidationError

from .helpers import cat, make_account
from .test_investments import PROVIDER

TODAY = date(2025, 6, 15)


@pytest.fixture
def setup(db):
    eur = make_account(db, "Corrente", "EUR", "5000", opened="2025-01-01")
    chf = make_account(db, "Svizzero", "CHF", "1000", opened="2025-01-01")
    with db.transaction() as conn:
        fx.store_rates(conn, "CHF", [(date(2025, 1, 1), Decimal("1.1"))], "yahoo")

    def op(kind, acc, amount, day, category, nature="expense"):
        tx.create(db, {"kind": kind, "account_id": acc["id"], "amount": amount, "date": day,
                       "category_id": cat(db, category, nature)})

    op("income", eur, "2000", "2025-05-27", "Stipendio", "income")
    op("expense", eur, "800", "2025-05-01", "Affitto")
    op("expense", eur, "100", "2025-05-10", "Ristoranti")
    op("expense", chf, "100", "2025-05-12", "Ristoranti")  # 110 EUR
    op("expense", eur, "50", "2025-06-02", "Svago")
    tx.create(db, {"kind": "transfer", "from_account_id": eur["id"], "to_account_id": chf["id"], "amount": "90",
                   "sent_amount": "100", "date": "2025-05-15", "fee_amount": "5"})
    return eur, chf


def test_expenses_by_category(db, setup):
    r = analytics.expenses_by_category(db, "2025-05-01", "2025-05-31")
    assert [(i["name"], i["eur"]) for i in r["items"]] == [
        ("Affitto", "800.00"), ("Ristoranti", "210.00"), ("Commissioni bancarie", "5.00")
    ]
    assert r["total"] == "1015.00" and r["missing"] == 0
    eur, _ = setup
    assert analytics.expenses_by_category(db, "2025-05-01", "2025-05-31", eur["id"])["total"] == "905.00"
    with pytest.raises(ValidationError):
        analytics.expenses_by_category(db, "2025-06-01", "2025-05-01")


def test_monthly_excludes_transfers_and_investments(db, setup):
    eur, _ = setup
    broker = make_account(db, "Broker", "EUR", "1000", opened="2025-01-01", behavior="investment")
    inv.create_asset(db, PROVIDER, broker["id"], {"ticker": "ETF.MI", "amount": "500", "date": "2025-05-20"})
    r = analytics.monthly(db, months=3, today=TODAY)
    assert [m["month"] for m in r["months"]] == ["2025-04", "2025-05", "2025-06"]
    may = r["months"][1]
    assert (may["income"], may["expenses"], may["net"]) == ("2000.00", "1015.00", "985.00")
    assert may["savings_rate"] == pytest.approx(49.25)
    assert r["months"][0]["savings_rate"] is None
    assert analytics.monthly(db, year=2025, today=TODAY)["months"][0]["month"] == "2025-01"


def test_account_report(db, setup):
    eur, chf = setup
    r = analytics.account_report(db, "2025-05-01", "2025-05-31")
    e = next(a for a in r["accounts"] if a["id"] == eur["id"])
    c = next(a for a in r["accounts"] if a["id"] == chf["id"])
    assert (e["income"], e["expenses"], e["transfers"], e["invested"]) == ("2000.00", "905.00", "-100.00", "0.00")
    assert (c["expenses"], c["expenses_eur"], c["transfers"], c["transfers_eur"]) == ("100.00", "110.00", "90.00", "99.00")


def test_missing_rates_are_counted(db):
    usd = make_account(db, "Dollari", "USD", "100", opened="2025-01-01")
    tx.create(db, {"kind": "expense", "account_id": usd["id"], "amount": "10", "date": "2025-05-01",
                   "category_id": cat(db, "Svago")})
    assert analytics.expenses_by_category(db, "2025-05-01", "2025-05-31")["missing"] == 1
    row = analytics.account_report(db, "2025-05-01", "2025-05-31")["accounts"][0]
    assert row["expenses"] == "10.00" and row["expenses_eur"] is None


def test_net_worth_monthly(db, setup):
    points = analytics.net_worth(db)["points"]
    assert points[0]["month"] == "2025-01"
    assert points[-1]["date"] == date.today().isoformat()


def test_analytics_api(server, db):
    _, client = server
    make_account(db, "Corrente", "EUR", "10")
    assert client.json("GET", "/api/analytics/categories?from=2025-01-01&to=2025-12-31")[0] == 200
    assert client.json("GET", "/api/analytics/categories?from=x&to=y")[0] == 400
    assert client.json("GET", "/api/analytics/categories?from=2025-01-01&to=2025-12-31&account=z")[0] == 400
    assert len(client.json("GET", "/api/analytics/monthly")[1]["months"]) == 12
    assert client.json("GET", "/api/analytics/accounts?from=2025-01-01&to=2025-12-31")[0] == 200
    assert client.json("GET", "/api/analytics/networth")[0] == 200
