from __future__ import annotations

from datetime import date, timedelta

import pytest

from mywealth import accounts
from mywealth.db import now_iso
from mywealth.errors import ConflictError, NotFoundError, ValidationError


def type_id(db, behavior="standard"):
    return next(t["id"] for t in accounts.list_types(db) if t["behavior"] == behavior and t["builtin"])


def new_account(db, **kw):
    data = {"name": "Conto", "bank": "Banca", "currency": "EUR", "opened_on": "2025-01-01",
            "opening_balance": "100,50", "type_id": type_id(db)}
    data.update(kw)
    return accounts.create_account(db, data)


def add_movement(db, acc_id, side="to", amount=1000, day="2025-02-01"):
    with db.transaction() as conn:
        now = now_iso()
        conn.execute(
            f"INSERT INTO transactions (kind, date, {side}_account_id, {side}_amount, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            ("income" if side == "to" else "expense", day, acc_id, amount, now, now),
        )


def test_builtin_types(db):
    types = accounts.list_types(db)
    assert {(t["name"], t["behavior"]) for t in types} == {
        ("Spese", "standard"), ("Salvadanaio", "savings"), ("Investimenti", "investment")
    }
    assert all(t["builtin"] for t in types)


def test_create_and_get(db):
    acc = new_account(db, name="  Conto   corrente ", currency="chf")
    assert acc["name"] == "Conto corrente"
    assert acc["currency"] == "CHF"
    assert acc["opening_balance"] == "100.50"
    assert acc["balance"] == "100.50"
    assert acc["type_name"] == "Spese"
    assert accounts.get_account(db, acc["id"]) == acc


def test_balance_is_derived(db):
    acc = new_account(db, opening_balance="100")
    add_movement(db, acc["id"], "to", 5050)
    add_movement(db, acc["id"], "from", 2000, "2025-03-01")
    assert accounts.get_account(db, acc["id"])["balance"] == "130.50"
    with db.connect() as conn:
        assert accounts.balance(conn, acc["id"], as_of="2025-02-15") == 15050
        assert accounts.balance(conn, acc["id"], as_of="2024-12-31") == 10000


def test_negative_opening_balance_allowed(db):
    assert new_account(db, opening_balance="-20")["balance"] == "-20.00"


@pytest.mark.parametrize(
    "bad",
    [
        {"name": ""},
        {"name": "x" * 81},
        {"currency": "XYZ"},
        {"opened_on": "31/02/2025"},
        {"opened_on": (date.today() + timedelta(days=1)).isoformat()},
        {"opening_balance": "12,3456"},
        {"type_id": 999},
        {"type_id": None},
    ],
)
def test_create_validation(db, bad):
    with pytest.raises(ValidationError):
        new_account(db, **bad)


def test_duplicate_name(db):
    new_account(db, name="Conto")
    with pytest.raises(ConflictError):
        new_account(db, name="conto")


def test_update(db):
    acc = new_account(db)
    out = accounts.update_account(db, acc["id"], {"bank": "Altra", "opening_balance": "0", "notes": "n"})
    assert (out["bank"], out["balance"], out["notes"]) == ("Altra", "0.00", "n")


def test_currency_change_blocked_with_movements(db):
    acc = new_account(db)
    assert accounts.update_account(db, acc["id"], {"currency": "USD"})["currency"] == "USD"
    add_movement(db, acc["id"])
    with pytest.raises(ConflictError):
        accounts.update_account(db, acc["id"], {"currency": "EUR"})


def test_currency_change_revalidates_opening_balance(db):
    acc = new_account(db, opening_balance="10,50")
    with pytest.raises(ValidationError):
        accounts.update_account(db, acc["id"], {"currency": "JPY"})


def test_opening_date_not_after_first_movement(db):
    acc = new_account(db, opened_on="2025-01-01")
    add_movement(db, acc["id"], day="2025-02-01")
    with pytest.raises(ValidationError):
        accounts.update_account(db, acc["id"], {"opened_on": "2025-03-01"})
    accounts.update_account(db, acc["id"], {"opened_on": "2025-02-01"})


def test_archive_and_delete(db):
    acc = new_account(db)
    add_movement(db, acc["id"])
    with pytest.raises(ConflictError):
        accounts.delete_account(db, acc["id"])
    assert accounts.update_account(db, acc["id"], {"archived": True})["archived"] is True
    assert accounts.list_accounts(db, include_archived=False) == []

    empty = new_account(db, name="Vuoto")
    accounts.delete_account(db, empty["id"])
    with pytest.raises(NotFoundError):
        accounts.get_account(db, empty["id"])


def test_custom_types(db):
    t = accounts.create_type(db, {"name": "Carta di credito", "behavior": "standard"})
    assert t["used"] == 0 and not t["builtin"]
    with pytest.raises(ConflictError):
        accounts.create_type(db, {"name": "carta di credito"})
    with pytest.raises(ValidationError):
        accounts.create_type(db, {"name": "X", "behavior": "magic"})
    t = accounts.update_type(db, t["id"], {"behavior": "savings", "name": "Deposito"})
    assert (t["name"], t["behavior"]) == ("Deposito", "savings")

    new_account(db, type_id=t["id"])
    with pytest.raises(ConflictError):
        accounts.update_type(db, t["id"], {"behavior": "standard"})
    with pytest.raises(ConflictError):
        accounts.delete_type(db, t["id"])
    with pytest.raises(ConflictError):
        accounts.delete_type(db, type_id(db))

    archived = accounts.create_type(db, {"name": "Vecchio"})
    accounts.update_type(db, archived["id"], {"archived": True})
    with pytest.raises(ValidationError):
        new_account(db, name="Nuovo", type_id=archived["id"])
    accounts.delete_type(db, archived["id"])


def test_accounts_api(server):
    _, client = server
    status, types = client.json("GET", "/api/account-types")
    assert status == 200
    body = {"name": "Conto", "currency": "EUR", "opened_on": "2025-01-01", "opening_balance": "1.000,00",
            "type_id": types[0]["id"]}
    status, acc = client.json("POST", "/api/accounts", body)
    assert status == 200 and acc["balance"] == "1000.00"
    assert client.json("POST", "/api/accounts", body)[0] == 409
    assert client.json("POST", "/api/accounts", {**body, "name": "B", "currency": "?"})[0] == 400
    status, acc = client.json("PUT", f"/api/accounts/{acc['id']}", {"name": "Nuovo"})
    assert acc["name"] == "Nuovo"
    assert [a["name"] for a in client.json("GET", "/api/accounts")[1]] == ["Nuovo"]
    assert client.json("DELETE", f"/api/accounts/{acc['id']}") == (200, {"ok": True})
    assert client.json("GET", f"/api/accounts/{acc['id']}")[0] == 404
    assert len(client.json("GET", "/api/currencies")[1]) > 10
