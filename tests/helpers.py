"""Shared builders for tests."""

from __future__ import annotations

from mywealth import accounts, categories


def type_id(db, behavior="standard"):
    return next(t["id"] for t in accounts.list_types(db) if t["behavior"] == behavior and t["builtin"])


def make_account(db, name="Conto", currency="EUR", opening="1000", opened="2025-01-01", behavior="standard", **kw):
    return accounts.create_account(db, {"name": name, "currency": currency, "opened_on": opened,
                                        "opening_balance": opening, "type_id": type_id(db, behavior), **kw})


def cat(db, name, nature="expense"):
    return next(c["id"] for c in categories.list_categories(db) if c["name"] == name and c["nature"] == nature)


def balance(db, acc_id):
    return accounts.get_account(db, acc_id)["balance"]
