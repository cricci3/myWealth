"""Import of bank statement CSVs through a column mapping.

Every bank exports a different CSV, so instead of hard-coding formats the user maps the
columns once (date, amount or debit/credit, description) and saves the mapping with the
bank's name. The rows are converted into the app's own CSV format and go through the
normal import (preview with errors and duplicates, all-or-nothing).
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal

from . import accounts, csvio, money
from .db import Database
from .errors import ValidationError

MAX_MAPPINGS = 30
DATE_FORMATS = {
    "dmy": ("%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%y", "%d.%m.%y"),
    "ymd": ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"),
    "mdy": ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y"),
}


def _table(text: str, delimiter: str | None = None) -> list[list[str]]:
    lines = [ln for ln in text.strip("﻿").splitlines()]
    if not delimiter:
        sample = "\n".join(lines[:20])
        counts = {d: sample.count(d) for d in (";", ",", "\t", "|")}
        delimiter = max(counts, key=counts.get)
    return [[c.strip() for c in row] for row in csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)]


def sample(raw: bytes, skip_rows: int = 0) -> dict:
    """First rows of the file, to let the user pick the columns."""
    rows = _table(csvio.decode(raw))
    rows = [r for r in rows[max(0, int(skip_rows)):] if any(r)]
    if not rows:
        raise ValidationError("Il file è vuoto.")
    return {"header": rows[0], "rows": rows[1:8], "count": len(rows) - 1}


def _int(value, name: str, required: bool = True) -> int | None:
    if value in (None, ""):
        if required:
            raise ValidationError(f"Scegli la colonna {name}.")
        return None
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"Colonna {name} non valida.") from None
    if v < 0:
        raise ValidationError(f"Colonna {name} non valida.")
    return v


def clean_mapping(m: dict) -> dict:
    out = {
        "name": " ".join(str(m.get("name") or "").split())[:60],
        "date_col": _int(m.get("date_col"), "data"),
        "description_col": _int(m.get("description_col"), "descrizione", required=False),
        "amount_col": _int(m.get("amount_col"), "importo", required=False),
        "debit_col": _int(m.get("debit_col"), "uscite", required=False),
        "credit_col": _int(m.get("credit_col"), "entrate", required=False),
        "date_format": m.get("date_format") if m.get("date_format") in DATE_FORMATS else "dmy",
        "skip_rows": max(0, min(int(m.get("skip_rows") or 0), 50)),
        "invert": bool(m.get("invert")),
    }
    if out["amount_col"] is None and out["debit_col"] is None and out["credit_col"] is None:
        raise ValidationError("Scegli la colonna dell'importo (oppure quelle di uscite ed entrate).")
    return out


def _amount(text: str) -> Decimal | None:
    s = (text or "").strip().replace("−", "-")
    if not s:
        return None
    negative = s.startswith("-") or s.endswith("-") or (s.startswith("(") and s.endswith(")"))
    s = re.sub(r"[()\-+\s]", "", s)
    s = re.sub(r"[A-Za-z€$£]", "", s)
    if not s:
        return None
    value = money.parse_decimal(s, "importo", grouping=True, max_places=2)
    return -value if negative else value


def _date(text: str, fmt: str) -> date:
    s = (text or "").strip().split(" ")[0]
    for f in DATE_FORMATS[fmt]:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    raise ValidationError(f"data '{text}' non riconosciuta")


def convert(db: Database, raw: bytes, mapping: dict, account_id, expense_category: str = "Altro",
            income_category: str = "Altro") -> str:
    """Bank rows -> CSV text in the app format, for csvio.preview / import_csv."""
    m = clean_mapping(mapping)
    acc = accounts.get_account(db, account_id)
    rows = _table(csvio.decode(raw))[m["skip_rows"]:]
    rows = [r for r in rows if any(r)]
    if len(rows) < 2:
        raise ValidationError("Nessuna riga dopo l'intestazione.")
    out = io.StringIO()
    w = csv.writer(out, delimiter=";", lineterminator="\n")
    w.writerow(csvio.COLUMNS)

    def cell(r, i):
        return r[i] if i is not None and i < len(r) else ""

    for r in rows[1:]:
        try:
            day = _date(cell(r, m["date_col"]), m["date_format"]).strftime("%d/%m/%Y")
        except ValidationError:
            day = cell(r, m["date_col"])  # left as is: the preview reports it on its line
        try:
            if m["amount_col"] is not None:
                value = _amount(cell(r, m["amount_col"]))
            else:
                debit = _amount(cell(r, m["debit_col"])) or Decimal(0)
                credit = _amount(cell(r, m["credit_col"])) or Decimal(0)
                value = credit - abs(debit)
        except ValidationError:
            value = None
        if value == 0:
            continue  # zero-amount lines (balances, notes) are skipped
        if value is None:
            raw_amount = cell(r, m["amount_col"]) if m["amount_col"] is not None else (
                cell(r, m["debit_col"]) or cell(r, m["credit_col"]))
            # written as is: the preview reports the invalid amount on its line
            w.writerow([day, "spesa", acc["name"], "", raw_amount or "?", "", expense_category,
                        cell(r, m["description_col"])])
            continue
        if m["invert"]:
            value = -value
        amount = f"{abs(value):.2f}".replace(".", ",")
        desc = " ".join(cell(r, m["description_col"]).split())[:200]
        if value < 0:
            w.writerow([day, "spesa", acc["name"], "", amount, "", expense_category, desc])
        else:
            w.writerow([day, "entrata", "", acc["name"], amount, "", income_category, desc])
    return out.getvalue()


def list_mappings(db: Database) -> list[dict]:
    return db.get_settings().get("bank_mappings", [])


def save_mapping(db: Database, mapping: dict) -> list[dict]:
    m = clean_mapping(mapping)
    if not m["name"]:
        raise ValidationError("Dai un nome alla mappatura (es. il nome della banca).")
    items = [x for x in list_mappings(db) if x.get("name", "").lower() != m["name"].lower()]
    items.append(m)
    if len(items) > MAX_MAPPINGS:
        raise ValidationError(f"Al massimo {MAX_MAPPINGS} mappature.")
    db.set_settings({"bank_mappings": sorted(items, key=lambda x: x["name"].lower())})
    return list_mappings(db)


def delete_mapping(db: Database, name: str) -> list[dict]:
    items = [x for x in list_mappings(db) if x.get("name", "").lower() != str(name).lower()]
    db.set_settings({"bank_mappings": items})
    return items
