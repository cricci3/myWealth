from __future__ import annotations

from mywealth import accounts, demo


def test_demo_seed(db):
    demo.seed(db)
    accs = accounts.list_accounts(db)
    assert {a["currency"] for a in accs} >= {"EUR", "CHF", "USD"}
    assert sum(a["behavior"] == "investment" for a in accs) == 2
    assert any(a["behavior"] == "savings" for a in accs)
