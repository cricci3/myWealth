"""PortfolioTracker import, bank CSV mappings, unlock PIN."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from mywealth import bankcsv, investments as inv, ptimport, security, transactions as tx
from mywealth.errors import ValidationError

from .helpers import balance, make_account
from .test_investments import PROVIDER

D0 = date.today() - timedelta(days=400)
D1 = date.today() - timedelta(days=200)


def portfolio(**over) -> bytes:
    data = {"schema": 1, "base_currency": "EUR", "assets": [
        {"id": "a1", "ticker": "ETF.MI", "name": "Demo ETF", "exchange": "MIL", "currency": "EUR",
         "input_symbol": "IE00TEST", "contributions": [
             {"id": "c1", "date": D0.isoformat(), "amount": 1000.0, "price": None, "note": ""},
             {"id": "c2", "date": D1.isoformat(), "amount": 500.5, "price": 11.0, "note": "PAC"}]},
    ]}
    data.update(over)
    return json.dumps(data).encode()


def test_pt_summary():
    s = ptimport.summary(portfolio())
    assert s["total"] == "1500.50" and s["contributions"] == 2 and s["first_date"] == D0.isoformat()
    with pytest.raises(ValidationError):
        ptimport.summary(b"{}")
    with pytest.raises(ValidationError):
        ptimport.summary(b"not json")


def test_pt_import_from_liquidity(db):
    broker = make_account(db, "Broker", "EUR", "2000", opened=(D0 - timedelta(days=5)).isoformat(), behavior="investment")
    out = ptimport.import_portfolio(db, portfolio(), broker["id"])
    assert out == {"assets": 1, "buys": 2, "transfers": 0}
    inv.refresh_prices(db, PROVIDER)
    a = inv.portfolio(db, broker["id"])["assets"][0]
    assert a["invested"] == "1500.50" and a["error"] is None
    assert a["trades"][1]["note"] == "PAC" and a["trades"][1]["price_input"] == "11"
    assert balance(db, broker["id"]) == "499.50"
    with pytest.raises(ValidationError, match="Già presenti"):
        ptimport.import_portfolio(db, portfolio(), broker["id"])


def test_pt_import_funded_by_transfers_or_rolled_back(db):
    broker = make_account(db, "Broker", "EUR", "0", opened=(D0 - timedelta(days=5)).isoformat(), behavior="investment")
    with pytest.raises(ValidationError, match="Liquidità"):
        ptimport.import_portfolio(db, portfolio(), broker["id"])
    assert inv.portfolio(db, broker["id"])["assets"] == []  # nothing half-imported
    bank = make_account(db, "Banca", "EUR", "5000", opened="2020-01-01")
    out = ptimport.import_portfolio(db, portfolio(), broker["id"], bank["id"])
    assert out["transfers"] == 2
    assert balance(db, broker["id"]) == "0.00" and balance(db, bank["id"]) == "3499.50"


def test_pt_import_currency_mismatch(db):
    usd = make_account(db, "US", "USD", "5000", opened=D0.isoformat(), behavior="investment")
    with pytest.raises(ValidationError, match="EUR"):
        ptimport.import_portfolio(db, portfolio(), usd["id"])


BANK = (
    "Estratto conto Banca Demo\n"
    "Data operazione;Data valuta;Descrizione;Uscite;Entrate\n"
    "05/03/2025;05/03/2025;PAGAMENTO POS SUPERMERCATO;45,90;\n"
    "27/03/2025;27/03/2025;STIPENDIO;;2.450,00\n"
    "28/03/2025;28/03/2025;SALDO;0;\n"
).encode("cp1252")


def test_bank_sample_and_convert(db):
    acc = make_account(db, "Corrente", "EUR", "100")
    s = bankcsv.sample(BANK, skip_rows=1)
    assert s["header"][0] == "Data operazione" and len(s["rows"]) == 3
    mapping = {"date_col": 0, "description_col": 2, "debit_col": 3, "credit_col": 4, "skip_rows": 1}
    text = bankcsv.convert(db, BANK, mapping, acc["id"])
    lines = text.strip().splitlines()
    assert len(lines) == 3  # header + 2 (zero line skipped)
    assert lines[1].startswith("05/03/2025;spesa;Corrente;;45,90")
    assert lines[2].startswith("27/03/2025;entrata;;Corrente;2450,00")
    from mywealth import csvio

    res = csvio.import_csv(db, text)
    assert res["imported"] == 2 and balance(db, acc["id"]) == "2504.10"


def test_bank_signed_amount_and_formats(db):
    acc = make_account(db, "Corrente", "EUR", "0")
    raw = b"Date,Amount,Text\n2025-03-05,-12.50,Coffee\n2025-03-06,100.00,Refund\n2025-03-07,abc,Broken\n"
    mapping = {"date_col": 0, "amount_col": 1, "description_col": 2, "date_format": "ymd"}
    from mywealth import csvio

    res = csvio.preview(db, bankcsv.convert(db, raw, mapping, acc["id"]))
    assert (res["valid"], res["errors"]) == (2, 1)
    inverted = csvio.preview(db, bankcsv.convert(db, raw, {**mapping, "invert": True}, acc["id"]))
    assert inverted["rows"][0]["kind"] == "income"
    with pytest.raises(ValidationError):
        bankcsv.convert(db, raw, {"date_col": 0}, acc["id"])


def test_bank_mappings(db):
    with pytest.raises(ValidationError, match="nome"):
        bankcsv.save_mapping(db, {"date_col": 0, "amount_col": 1})
    bankcsv.save_mapping(db, {"name": "Banca Demo", "date_col": 0, "amount_col": 1})
    bankcsv.save_mapping(db, {"name": "banca demo", "date_col": 1, "amount_col": 2})  # replaced
    items = bankcsv.list_mappings(db)
    assert len(items) == 1 and items[0]["date_col"] == 1
    assert bankcsv.delete_mapping(db, "BANCA DEMO") == []


def test_pin(db):
    gate = security.Gate()
    assert not gate.locked(db)
    with pytest.raises(ValidationError):
        security.set_pin(db, "12", None)
    security.set_pin(db, "1234", None)
    assert gate.locked(db)
    with pytest.raises(security.LockedError):
        gate.unlock(db, "0000")
    gate.unlock(db, "1234")
    assert not gate.locked(db)
    with pytest.raises(ValidationError, match="attuale"):
        security.set_pin(db, "5678", "0000")
    security.set_pin(db, "", "1234")
    assert not security.is_set(db)


def test_pin_attempts_are_limited(db, monkeypatch):
    security.set_pin(db, "1234", None)
    gate = security.Gate()
    for _ in range(security.MAX_FAILURES):
        with pytest.raises(security.LockedError):
            gate.unlock(db, "9999")
    with pytest.raises(security.LockedError, match="riprova"):
        gate.unlock(db, "1234")  # blocked even with the right PIN


def test_pin_locks_the_api(server, db):
    httpd, client = server
    assert client.json("PUT", "/api/pin", {"new": "2468"}) == (200, {"pin_set": True})
    client.json("POST", "/api/lock")
    assert client.json("GET", "/api/accounts")[0] == 423
    assert client.json("PUT", "/api/settings", {"theme": "dark"})[0] == 423
    assert client.json("GET", "/api/settings")[0] == 200
    assert client.json("GET", "/api/lock")[1] == {"pin_set": True, "locked": True}
    assert client.json("POST", "/api/unlock", {"pin": "1111"})[0] == 423
    assert client.json("POST", "/api/unlock", {"pin": "2468"})[0] == 200
    assert client.json("GET", "/api/accounts")[0] == 200


def test_m11_api(server, db):
    _, client = server
    acc = make_account(db, "Corrente", "EUR", "0")
    assert client.json("POST", "/api/import/bank/sample?skip_rows=1", BANK)[1]["count"] == 3
    mapping = json.dumps({"date_col": 0, "description_col": 2, "debit_col": 3, "credit_col": 4, "skip_rows": 1})
    from urllib.parse import quote

    q = f"mapping={quote(mapping)}&account={acc['id']}"
    assert client.json("POST", f"/api/import/bank/preview?{q}", BANK)[1]["valid"] == 2
    assert client.json("POST", f"/api/import/bank?{q}", BANK)[1]["imported"] == 2
    assert client.json("POST", "/api/import/bank/mappings", {"name": "Demo", "date_col": 0, "amount_col": 1})[0] == 200
    assert client.json("DELETE", "/api/import/bank/mappings/Demo")[1] == []
    broker = make_account(db, "Broker", "EUR", "5000", opened=D0.isoformat(), behavior="investment")
    assert client.json("POST", f"/api/investments/{broker['id']}/portfoliotracker/preview", portfolio())[0] == 200
    status, out = client.json("POST", f"/api/investments/{broker['id']}/portfoliotracker", portfolio())
    assert status == 200 and out["buys"] == 2
    assert tx.list_transactions(db, {"kind": "buy"})["total"] == 2
