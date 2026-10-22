from __future__ import annotations

from datetime import date

import pytest

from mywealth import accounts, savings, settings, transactions as tx
from mywealth.errors import ValidationError

from .helpers import balance, cat, make_account

MARCH = date(2025, 3, 15)


def piggy(db, opening="12000", opened="2025-01-01", rate="3", rate_from=None):
    acc = make_account(db, "Salvadanaio", "EUR", opening, opened=opened, behavior="savings")
    if rate is not None:
        savings.add_rate(db, acc["id"], {"annual_rate": rate, "valid_from": rate_from or opened})
    return acc


def interest(db, acc_id):
    items = tx.list_transactions(db, {"account": acc_id, "kind": "interest"})["items"]
    return sorted((t["date"], t["amount"]) for t in items)


def deposit(db, acc_id, amount, day):
    src = make_account(db, f"Fonte {day}", "EUR", "100000", opened="2024-01-01")
    tx.create(db, {"kind": "transfer", "from_account_id": src["id"], "to_account_id": acc_id, "amount": amount,
                   "date": day})


def test_full_month_and_monthly_compounding(db):
    acc = piggy(db)
    created = savings.generate(db, today=MARCH)
    assert [c["month"] for c in created] == ["2025-01", "2025-02"]
    # Jan: 12000 × 3% / 12 = 30.00; Feb: 12030 × 3% / 12 = 30.075 -> 30.08
    assert interest(db, acc["id"]) == [("2025-01-31", "30.00"), ("2025-02-28", "30.08")]
    assert balance(db, acc["id"]) == "12060.08"
    t = tx.list_transactions(db, {"kind": "interest"})["items"][0]
    assert t["auto"] and t["category_name"] == "Interessi" and t["description"] == "Interessi febbraio 2025"


def test_generation_is_idempotent_and_respects_deletions(db):
    acc = piggy(db)
    savings.generate(db, today=MARCH)
    assert savings.generate(db, today=MARCH) == []
    first = tx.list_transactions(db, {"kind": "interest"})["items"][-1]
    tx.delete(db, first["id"])
    assert savings.generate(db, today=MARCH) == []
    assert len(interest(db, acc["id"])) == 1
    # the next month is generated once it's over
    assert [c["month"] for c in savings.generate(db, today=date(2025, 4, 1))] == ["2025-03"]


def test_daily_balance_deposit_mid_month(db):
    acc = piggy(db, opening="0", rate="2.4")
    deposit(db, acc["id"], "3100", "2025-01-17")  # counted from the 17th: 15 days of 31
    savings.generate(db, today=date(2025, 2, 1))
    assert interest(db, acc["id"]) == [("2025-01-31", "3.00")]


def test_account_opened_mid_month(db):
    acc = piggy(db, opening="3100", opened="2025-01-22", rate="2,4")  # 10 days of 31
    savings.generate(db, today=date(2025, 2, 1))
    assert interest(db, acc["id"]) == [("2025-01-31", "2.00")]


def test_rate_change_mid_month(db):
    acc = piggy(db, opening="3100", rate="2.4")
    savings.add_rate(db, acc["id"], {"annual_rate": "4.8", "valid_from": "2025-01-17"})
    savings.generate(db, today=date(2025, 2, 1))
    assert interest(db, acc["id"]) == [("2025-01-31", "9.20")]  # 16 × 0.20 + 15 × 0.40


def test_no_interest_before_first_rate_or_on_negative_balance(db):
    acc = piggy(db, opening="12000", rate="3", rate_from="2025-02-01")
    savings.generate(db, today=MARCH)
    assert interest(db, acc["id"]) == [("2025-02-28", "30.00")]

    neg = make_account(db, "Rosso", "EUR", "-500", opened="2025-01-01", behavior="savings")
    savings.add_rate(db, neg["id"], {"annual_rate": "5", "valid_from": "2025-01-01"})
    savings.generate(db, today=MARCH)
    assert interest(db, neg["id"]) == []


def test_withholding_tax(db):
    settings.update(db, {"interest_tax_enabled": True, "interest_tax_rate": "26"})
    acc = piggy(db)
    savings.generate(db, today=date(2025, 2, 1))
    assert interest(db, acc["id"]) == [("2025-01-31", "22.20")]  # 30.00 - 7.80
    month = savings.overview(db, acc["id"])["months"][0]
    assert (month["gross"], month["tax"], month["credited"]) == ("30.00", "7.80", "22.20")
    assert "ritenuta 7.80" in tx.list_transactions(db, {"kind": "interest"})["items"][0]["description"]


def test_recalculate_after_backdated_deposit(db):
    acc = piggy(db, opening="0", rate="2.4")
    savings.generate(db, today=MARCH)
    assert interest(db, acc["id"]) == []
    deposit(db, acc["id"], "3100", "2025-02-01")
    assert savings.generate(db, today=MARCH) == []  # months already computed
    created = savings.recalculate(db, acc["id"], "2025-02", today=MARCH)
    assert [c["month"] for c in created] == ["2025-02"]
    assert interest(db, acc["id"]) == [("2025-02-28", "6.20")]  # 3100 × 2.4% / 12
    with pytest.raises(ValidationError):
        savings.recalculate(db, acc["id"], "febbraio")


def test_archived_accounts_are_skipped(db):
    acc = piggy(db)
    accounts.update_account(db, acc["id"], {"archived": True})
    assert savings.generate(db, today=MARCH) == []


def test_rates_validation_and_history(db):
    acc = piggy(db, rate=None)
    with pytest.raises(ValidationError):
        savings.add_rate(db, acc["id"], {"annual_rate": "-1"})
    with pytest.raises(ValidationError):
        savings.add_rate(db, acc["id"], {"annual_rate": "abc"})
    std = make_account(db, "Corrente", "EUR", "0")
    with pytest.raises(ValidationError):
        savings.add_rate(db, std["id"], {"annual_rate": "1"})
    # a rate before the opening date starts at the opening
    assert savings.add_rate(db, acc["id"], {"annual_rate": "10", "valid_from": "2020-01-01"})["valid_from"] == "2025-01-01"
    savings.add_rate(db, acc["id"], {"annual_rate": "2,5", "valid_from": "2025-06-01"})
    rates = savings.list_rates(db, acc["id"])
    assert [(r["annual_rate"], r["valid_from"]) for r in rates] == [("10", "2025-01-01"), ("2.5", "2025-06-01")]
    assert accounts.get_account(db, acc["id"])["behavior"] == "savings"
    assert next(a for a in accounts.list_accounts(db) if a["id"] == acc["id"])["annual_rate"] == "2.5"
    savings.delete_rate(db, acc["id"], rates[0]["id"])
    assert len(savings.list_rates(db, acc["id"])) == 1


def test_interest_operation_is_editable(db):
    acc = piggy(db)
    savings.generate(db, today=date(2025, 2, 1))
    t = tx.list_transactions(db, {"kind": "interest"})["items"][0]
    assert t["editable"]
    out = tx.update(db, t["id"], {"account_id": acc["id"], "amount": "29,50", "date": t["date"],
                                  "description": t["description"]})
    assert out["amount"] == "29.50" and out["category_name"] == "Interessi"


def test_savings_api(server, db):
    _, client = server
    acc = piggy(db, rate=None, opened="2025-01-01")
    status, data = client.json("POST", f"/api/savings/{acc['id']}/rates", {"annual_rate": "3", "valid_from": "2025-01-01"})
    assert status == 200 and data["generated"]  # past months are credited right away
    status, ov = client.json("GET", f"/api/savings/{acc['id']}")
    assert ov["current_rate"] == "3" and ov["months"]
    assert client.json("POST", f"/api/savings/{acc['id']}/recalculate", {"from_month": "2025-01"})[0] == 200
    assert client.json("PUT", "/api/settings", {"interest_tax_rate": "101"})[0] == 400
    assert client.json("PUT", "/api/settings", {"interest_tax_rate": "12,5"})[1]["interest_tax_rate"] == "12.5"
    assert client.json("GET", f"/api/savings/{make_account(db, 'X', 'EUR', '0')['id']}")[0] == 400
    assert cat(db, "Interessi", "income")
