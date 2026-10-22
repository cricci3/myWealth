from __future__ import annotations

from datetime import date, timedelta

import pytest

from mywealth import categories, transactions as tx
from mywealth.errors import ConflictError, NotFoundError, ValidationError

from .helpers import balance, cat, make_account


@pytest.fixture
def eur(db):
    return make_account(db, "Corrente", "EUR", "1000")


@pytest.fixture
def chf(db):
    return make_account(db, "Svizzero", "CHF", "500")


def expense(db, acc, amount="10", **kw):
    return tx.create(db, {"kind": "expense", "account_id": acc["id"], "amount": amount, "date": "2025-03-01",
                          "category_id": cat(db, "Ristoranti"), "description": "Pizza", **kw})


def test_expense_and_income_update_balance(db, eur):
    t = expense(db, eur, "25,50")
    assert (t["kind"], t["amount"], t["currency"], t["account_name"]) == ("expense", "25.50", "EUR", "Corrente")
    assert t["eur"] == "25.50" and t["from_rate"] == "1"
    assert t["warnings"] == []
    tx.create(db, {"kind": "income", "account_id": eur["id"], "amount": "1.500", "date": "2025-03-27",
                   "category_id": cat(db, "Stipendio", "income")})
    assert balance(db, eur["id"]) == "2474.50"


def test_non_eur_without_rate_has_no_eur_value_yet(db, chf):
    t = expense(db, chf)
    assert t["currency"] == "CHF" and t["eur"] is None and t["from_rate"] is None


def test_negative_balance_allowed_with_warning(db, eur):
    t = expense(db, eur, "1200")
    assert balance(db, eur["id"]) == "-200.00"
    assert "negativo" in t["warnings"][0]


@pytest.mark.parametrize(
    "change, msg",
    [
        ({"amount": "0"}, "maggiore di zero"),
        ({"amount": "-5"}, "positivo"),
        ({"amount": "1,234"}, None),  # valid (thousands) -> no error
        ({"date": (date.today() + timedelta(days=1)).isoformat()}, "futuro"),
        ({"date": "2024-12-31"}, "aperto"),
        ({"category_id": None}, "categoria"),
        ({"account_id": 999}, "Conto"),
        ({"description": "x" * 201}, "lunga"),
    ],
)
def test_expense_validation(db, eur, change, msg):
    if msg is None:
        expense(db, eur, **change)
        return
    with pytest.raises(ValidationError, match=msg):
        expense(db, eur, **change)


def test_category_nature_must_match(db, eur):
    with pytest.raises(ValidationError, match="adatta"):
        expense(db, eur, category_id=cat(db, "Stipendio", "income"))


def test_archived_account_rejected_for_new_ops_but_kept_on_edit(db, eur):
    from mywealth import accounts

    t = expense(db, eur)
    accounts.update_account(db, eur["id"], {"archived": True})
    with pytest.raises(ValidationError, match="archiviato"):
        expense(db, eur)
    out = tx.update(db, t["id"], {"account_id": eur["id"], "amount": "12", "date": "2025-03-02",
                                  "category_id": cat(db, "Ristoranti")})
    assert out["amount"] == "12.00"


def test_transfer_same_currency(db, eur):
    other = make_account(db, "Risparmi", "EUR", "0")
    t = tx.create(db, {"kind": "transfer", "from_account_id": eur["id"], "to_account_id": other["id"],
                       "amount": "300", "date": "2025-03-01"})
    assert t["description"] == "Trasferimento da Corrente a Risparmi"
    assert t["category_name"] == "Trasferimento"
    assert (t["from_amount"], t["to_amount"]) == ("300.00", "300.00")
    assert balance(db, eur["id"]) == "700.00" and balance(db, other["id"]) == "300.00"


def test_transfer_between_currencies_needs_both_amounts(db, eur, chf):
    base = {"kind": "transfer", "from_account_id": eur["id"], "to_account_id": chf["id"], "amount": "93,50",
            "date": "2025-03-01"}
    with pytest.raises(ValidationError, match="inviato"):
        tx.create(db, base)
    t = tx.create(db, {**base, "sent_amount": "100"})
    assert (t["from_amount"], t["from_currency"], t["to_amount"], t["to_currency"]) == ("100.00", "EUR", "93.50", "CHF")
    assert balance(db, eur["id"]) == "900.00" and balance(db, chf["id"]) == "593.50"


def test_transfer_to_same_account_rejected(db, eur):
    with pytest.raises(ValidationError, match="diverso"):
        tx.create(db, {"kind": "transfer", "from_account_id": eur["id"], "to_account_id": eur["id"],
                       "amount": "1", "date": "2025-03-01"})


def test_transfer_fee_lifecycle(db, eur, chf):
    base = {"kind": "transfer", "from_account_id": eur["id"], "to_account_id": chf["id"], "amount": "90",
            "sent_amount": "100", "date": "2025-03-01", "fee_amount": "2,50", "fee_side": "from"}
    t = tx.create(db, base)
    assert t["fee"] == {"id": t["fee"]["id"], "side": "from", "amount": "2.50", "currency": "EUR"}
    assert balance(db, eur["id"]) == "897.50"
    fee = tx.get(db, t["fee"]["id"])
    assert fee["kind"] == "fee" and fee["category_name"] == "Commissioni bancarie" and fee["linked_id"] == t["id"]
    assert not fee["editable"]
    with pytest.raises(ConflictError):
        tx.update(db, fee["id"], {"amount": "1"})

    # fee moves to the destination account, in its currency
    t = tx.update(db, t["id"], {**base, "fee_amount": "3", "fee_side": "to"})
    assert t["fee"]["side"] == "to" and t["fee"]["currency"] == "CHF"
    assert balance(db, eur["id"]) == "900.00" and balance(db, chf["id"]) == "587.00"

    # removing the fee from the transfer deletes it
    t = tx.update(db, t["id"], {**base, "fee_amount": ""})
    assert t["fee"] is None
    with pytest.raises(NotFoundError):
        tx.get(db, fee["id"])

    # deleting the transfer deletes its fee
    t = tx.update(db, t["id"], {**base})
    fee_id = t["fee"]["id"]
    tx.delete(db, t["id"])
    with pytest.raises(NotFoundError):
        tx.get(db, fee_id)
    assert balance(db, eur["id"]) == "1000.00" and balance(db, chf["id"]) == "500.00"


def test_kind_cannot_change_and_must_be_user_kind(db, eur):
    with pytest.raises(ValidationError):
        tx.create(db, {"kind": "interest", "account_id": eur["id"], "amount": "1"})
    t = expense(db, eur)
    out = tx.update(db, t["id"], {"kind": "income", "account_id": eur["id"], "amount": "5", "date": "2025-03-01",
                                  "category_id": cat(db, "Svago")})
    assert out["kind"] == "expense"


def test_list_filters_and_paging(db, eur, chf):
    for i in range(35):
        expense(db, eur, str(i + 1), date=f"2025-03-{(i % 28) + 1:02d}", description=f"Spesa {i}")
    tx.create(db, {"kind": "income", "account_id": chf["id"], "amount": "100", "date": "2025-04-01",
                   "category_id": cat(db, "Rimborsi", "income"), "description": "Rimborso 100%"})
    page = tx.list_transactions(db)
    assert len(page["items"]) == 30 and page["has_more"] and page["total"] == 36
    assert page["items"][0]["description"] == "Rimborso 100%"  # newest first
    rest = tx.list_transactions(db, offset=30)
    assert len(rest["items"]) == 6 and not rest["has_more"]

    assert tx.list_transactions(db, {"account": chf["id"]})["total"] == 1
    assert tx.list_transactions(db, {"kind": "income"})["total"] == 1
    assert tx.list_transactions(db, {"category": cat(db, "Ristoranti")})["total"] == 35
    assert tx.list_transactions(db, {"from": "2025-03-27", "to": "2025-03-28"})["total"] == 2
    assert tx.list_transactions(db, {"q": "100%"})["total"] == 1
    assert tx.list_transactions(db, {"q": "_"})["total"] == 0
    with pytest.raises(ValidationError):
        tx.list_transactions(db, {"account": "x"})


def test_transfer_fees_hidden_from_default_list(db, eur, chf):
    tx.create(db, {"kind": "transfer", "from_account_id": eur["id"], "to_account_id": chf["id"], "amount": "90",
                   "sent_amount": "100", "date": "2025-03-01", "fee_amount": "1"})
    assert [t["kind"] for t in tx.list_transactions(db)["items"]] == ["transfer"]
    assert tx.list_transactions(db, {"kind": "fee"})["total"] == 1


def test_categories_crud_and_delete_with_move(db, eur):
    c = categories.create_category(db, {"name": "Palestra", "nature": "expense"})
    with pytest.raises(ConflictError):
        categories.create_category(db, {"name": "palestra", "nature": "expense"})
    categories.create_category(db, {"name": "Palestra", "nature": "income"})  # other nature: fine
    t = expense(db, eur, category_id=c["id"])
    with pytest.raises(ValidationError, match="spostare"):
        categories.delete_category(db, c["id"])
    with pytest.raises(ValidationError):
        categories.delete_category(db, c["id"], cat(db, "Stipendio", "income"))
    categories.delete_category(db, c["id"], cat(db, "Svago"))
    assert tx.get(db, t["id"])["category_name"] == "Svago"

    fees = cat(db, "Commissioni bancarie")
    with pytest.raises(ConflictError):
        categories.delete_category(db, fees)
    with pytest.raises(ConflictError):
        categories.update_category(db, fees, {"archived": True})
    assert categories.update_category(db, fees, {"name": "Commissioni"})["name"] == "Commissioni"

    svago = cat(db, "Svago")
    categories.update_category(db, svago, {"archived": True})
    with pytest.raises(ValidationError, match="archiviata"):
        expense(db, eur, category_id=svago)
    # an operation already in an archived category keeps it when edited
    tx.update(db, t["id"], {"account_id": eur["id"], "amount": "1", "date": "2025-03-01", "category_id": svago})


def test_account_with_operations_cannot_be_deleted(db, eur):
    from mywealth import accounts

    expense(db, eur)
    with pytest.raises(ConflictError):
        accounts.delete_account(db, eur["id"])
    assert accounts.get_account(db, eur["id"])["movements"] == 1


def test_transactions_api(server):
    _, client = server
    _, types = client.json("GET", "/api/account-types")
    _, acc = client.json("POST", "/api/accounts", {"name": "A", "currency": "EUR", "opened_on": "2025-01-01",
                                                    "type_id": types[0]["id"]})
    _, cats = client.json("GET", "/api/categories")
    food = next(c for c in cats if c["name"] == "Spesa alimentare")
    status, t = client.json("POST", "/api/transactions", {"kind": "expense", "account_id": acc["id"], "amount": "5",
                                                           "date": "2025-02-01", "category_id": food["id"]})
    assert status == 200 and t["warnings"]
    assert client.json("GET", "/api/transactions?limit=1")[1]["items"][0]["id"] == t["id"]
    assert client.json("GET", "/api/transactions?account=abc")[0] == 400
    body = {"account_id": acc["id"], "amount": "6", "date": "2025-02-01", "category_id": food["id"]}
    assert client.json("PUT", f"/api/transactions/{t['id']}", body)[1]["amount"] == "6.00"
    assert client.json("DELETE", f"/api/categories/{food['id']}")[0] == 400
    assert client.json("DELETE", f"/api/transactions/{t['id']}") == (200, {"ok": True})
    assert client.json("DELETE", f"/api/categories/{food['id']}") == (200, {"ok": True})
