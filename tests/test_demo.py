from __future__ import annotations

from mywealth import accounts, demo


def test_demo_seed(db):
    demo.seed(db)
    accs = accounts.list_accounts(db)
    assert {a["currency"] for a in accs} >= {"EUR", "CHF", "USD"}
    assert sum(a["behavior"] == "investment" for a in accs) == 2
    assert any(a["behavior"] == "savings" for a in accs)


def test_demo_has_a_year_of_operations_and_no_negative_balance(db):
    from mywealth import transactions

    demo.seed(db)
    assert transactions.list_transactions(db)["total"] > 200
    assert all(a["balance_minor"] >= 0 for a in accounts.list_accounts(db))


def test_demo_savings_interest(db):
    from mywealth import savings

    demo.seed(db)
    assert len(savings.generate(db)) >= 11


def test_demo_investments(db):
    from mywealth import investments

    demo.seed(db)
    for acc in investments.list_accounts(db):
        p = investments.portfolio(db, acc["id"])
        assert p["assets"] and all(a["error"] is None for a in p["assets"])
        assert float(p["summary"]["liquidity"]) >= 0
