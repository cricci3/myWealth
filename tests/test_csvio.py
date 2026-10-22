from __future__ import annotations

import csv
import io
import json

import pytest

from mywealth import csvio, transactions as tx
from mywealth.errors import ValidationError

from .helpers import balance, cat, make_account

HEADER = "data;tipo;conto_origine;conto_destinazione;importo;importo_destinazione;categoria;descrizione\n"


@pytest.fixture
def accs(db):
    return (make_account(db, "Corrente", "EUR", "1000"), make_account(db, "Svizzero", "CHF", "100"),
            make_account(db, "Risparmi", "EUR", "0"))


def test_import_all_kinds(db, accs):
    text = HEADER + (
        "05/03/2025;spesa;Corrente;;45,90;;Spesa alimentare;Supermercato\n"
        "2025-03-27;entrata;;corrente;1.000,00;;Stipendio;Stipendio\n"
        "28/03/2025;trasferimento;Corrente;Risparmi;300;;;Risparmio\n"
        "10/04/2025;trasferimento;Corrente;Svizzero;100,00;94,20;;Cambio\n"
    )
    res = csvio.import_csv(db, text)
    assert res["imported"] == 4 and res["errors"] == 0
    assert balance(db, accs[0]["id"]) == "1554.10"
    assert balance(db, accs[1]["id"]) == "194.20"
    assert balance(db, accs[2]["id"]) == "300.00"


def test_comma_separator_and_dot_decimals(db, accs):
    text = HEADER.replace(";", ",") + "05/03/2025,spesa,Corrente,,45.90,,Svago,Cinema\n"
    assert csvio.import_csv(db, text)["imported"] == 1


def test_preview_reports_errors_per_row_and_saves_nothing(db, accs):
    text = HEADER + (
        "05/03/2025;spesa;Corrente;;10;;Svago;ok\n"
        "31/02/2025;spesa;Corrente;;10;;Svago;data\n"
        "05/03/2025;spesa;Inesistente;;10;;Svago;conto\n"
        "05/03/2025;regalo;Corrente;;10;;Svago;tipo\n"
        "05/03/2025;spesa;Corrente;;-3;;Svago;importo\n"
        "05/03/2025;trasferimento;Corrente;Svizzero;10;;;valute\n"
    )
    res = csvio.preview(db, text)
    assert (res["total"], res["valid"], res["errors"]) == (6, 1, 5)
    msgs = [r["errors"][0] if r["errors"] else "" for r in res["rows"]]
    assert "data" in msgs[1] and "inesistente" in msgs[2] and "tipo" in msgs[3] and "positivo" in msgs[4]
    assert "importo_destinazione" in msgs[5]
    assert tx.list_transactions(db)["total"] == 0
    with pytest.raises(ValidationError, match="Nessuna operazione importata"):
        csvio.import_csv(db, text)
    assert tx.list_transactions(db)["total"] == 0  # all or nothing


def test_unknown_category_can_be_created(db, accs):
    text = HEADER + "05/03/2025;spesa;Corrente;;10;;Palestra;Abbonamento\n"
    res = csvio.preview(db, text)
    assert res["new_categories"] == [{"name": "Palestra", "nature": "expense"}] and res["errors"] == 1
    res = csvio.preview(db, text, create_categories=True)
    assert res["errors"] == 0
    with pytest.raises(StopIteration):
        cat(db, "Palestra")  # the preview created nothing
    csvio.import_csv(db, text, create_categories=True)
    assert cat(db, "Palestra")


def test_duplicates_are_flagged(db, accs):
    row = "05/03/2025;spesa;Corrente;;10;;Svago;Cinema\n"
    csvio.import_csv(db, HEADER + row)
    res = csvio.preview(db, HEADER + row + row.replace("Cinema", "cinema "))
    assert res["duplicates"] == 2
    assert "già presente" in res["rows"][0]["warnings"][0]


@pytest.mark.parametrize("text", ["", "a;b;c\n1;2;3\n", HEADER])
def test_bad_files(db, text):
    with pytest.raises(ValidationError):
        csvio.preview(db, text)


def test_decode():
    assert csvio.decode("﻿data".encode("utf-8")) == "data"
    assert csvio.decode("perché".encode("cp1252")) == "perché"


def test_operations_export_round_trip(db, accs):
    text = HEADER + (
        "05/03/2025;spesa;Corrente;;45,90;;Spesa alimentare;Supermercato\n"
        "10/04/2025;trasferimento;Corrente;Svizzero;100,00;94,20;;Cambio\n"
    )
    csvio.import_csv(db, text)
    body, name, ext = csvio.export(db, "operazioni", "csv", {})
    assert name.endswith(".csv") and ext == "csv"
    exported = body.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(exported), delimiter=";"))
    assert rows[0][:8] == csvio.COLUMNS and rows[1][:5] == ["05/03/2025", "spesa", "Corrente", "", "45,90"]
    # the export can be imported again (into a fresh copy of the accounts)
    res = csvio.preview(db, exported)
    assert res["errors"] == 0 and res["duplicates"] == 2


@pytest.mark.parametrize("what", ["operazioni", "conti", "categorie", "investimenti", "report-mensile"])
def test_all_exports(db, accs, what):
    tx.create(db, {"kind": "expense", "account_id": accs[0]["id"], "amount": "5", "date": "2025-03-01",
                   "category_id": cat(db, "Svago")})
    body, _, _ = csvio.export(db, what, "csv", {"from": "2025-01-01", "to": "2025-04-30"})
    assert body.startswith("﻿".encode("utf-8"))
    body, _, _ = csvio.export(db, what, "json", {"from": "2025-01-01", "to": "2025-04-30"})
    assert json.loads(body) is not None
    with pytest.raises(ValidationError):
        csvio.export(db, what, "xml", {})


def test_import_api(server, db, accs):
    _, client = server
    text = (HEADER + "05/03/2025;spesa;Corrente;;10;;Nuova;x\n").encode("utf-8")
    status, res = client.json("POST", "/api/import/preview", text)
    assert status == 200 and res["errors"] == 1
    assert client.json("POST", "/api/import/csv", text)[0] == 400
    status, res = client.json("POST", "/api/import/csv?create_categories=1", text)
    assert status == 200 and res["imported"] == 1
    status, headers, body = client.request("GET", "/api/import/template")
    assert status == 200 and "attachment" in headers["Content-Disposition"]
    assert csvio.preview(db, body.decode("utf-8-sig"))["total"] == 4
    status, headers, _ = client.request("GET", "/api/export/conti?format=json")
    assert status == 200 and headers["Content-Type"].startswith("application/json")
    assert client.request("GET", "/api/export/nope")[0] == 400
