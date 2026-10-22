"""CSV import of operations (the app's own format) and CSV/JSON exports.

Import format, one operation per row, with a header:
    data;tipo;conto_origine;conto_destinazione;importo;importo_destinazione;categoria;descrizione
- separator `;` or `,`; decimals with comma or dot; dates dd/mm/yyyy or yyyy-mm-dd;
- tipo: spesa | entrata | trasferimento;
- spesa: conto_origine + importo; entrata: conto_destinazione + importo;
  trasferimento: both accounts, importo in the origin currency and, between different
  currencies, importo_destinazione (received);
- extra columns are ignored, so an operations export can be imported again.
The import runs in one transaction: either every row is saved or none.

Files from the smartphone (SPEC §16) add an `id` column (UUID given by the phone) and
`creato_il`: with `track_ids` rows whose id was already imported are skipped, and the ids
of the imported rows are recorded, so sending the same entries twice creates no duplicates.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import uuid
from datetime import date

from . import analytics, investments, money, transactions
from .db import Database, now_iso
from .errors import ValidationError

COLUMNS = ["data", "tipo", "conto_origine", "conto_destinazione", "importo", "importo_destinazione", "categoria",
           "descrizione"]
KINDS = {"spesa": "expense", "uscita": "expense", "expense": "expense", "entrata": "income", "income": "income",
         "trasferimento": "transfer", "transfer": "transfer"}
NATURE = {"expense": "expense", "income": "income", "transfer": "transfer"}
MAX_ROWS = 20_000

TEMPLATE = (
    "data;tipo;conto_origine;conto_destinazione;importo;importo_destinazione;categoria;descrizione\r\n"
    "05/03/2026;spesa;Conto corrente;;45,90;;Spesa alimentare;Supermercato\r\n"
    "27/03/2026;entrata;;Conto corrente;2.450,00;;Stipendio;Stipendio marzo\r\n"
    "28/03/2026;trasferimento;Conto corrente;Salvadanaio;300,00;;Trasferimento;Risparmio mensile\r\n"
    "10/04/2026;trasferimento;Conto corrente;Conto svizzero;100,00;94,20;;Cambio in CHF\r\n"
)


def decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValidationError("Il file non è un testo leggibile (usa UTF-8).")


def _rows(text: str) -> list[dict]:
    lines = text.strip("﻿").splitlines()
    if not lines or not lines[0].strip():
        raise ValidationError("Il file è vuoto.")
    header = lines[0]
    delimiter = ";" if header.count(";") >= header.count(",") else ","
    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    fields = [(f or "").strip().lower() for f in (reader.fieldnames or [])]
    missing = [c for c in ("data", "tipo", "importo") if c not in fields]
    if missing:
        raise ValidationError(f"Intestazione non valida: mancano le colonne {', '.join(missing)}. Scarica il modello.")
    reader.fieldnames = fields
    out = []
    for i, row in enumerate(reader, start=2):
        if i - 1 > MAX_ROWS:
            raise ValidationError(f"Troppe righe (max {MAX_ROWS}).")
        clean = {k: (v or "").strip() for k, v in row.items() if k}
        if not any(clean.values()):
            continue
        clean["_line"] = i
        out.append(clean)
    if not out:
        raise ValidationError("Nessuna operazione nel file.")
    return out


def _lookup(conn: sqlite3.Connection):
    accs = {r["name"].lower(): r for r in conn.execute("SELECT id, name, currency, archived FROM accounts")}
    cats = {(r["name"].lower(), r["nature"]): r for r in conn.execute("SELECT id, name, nature, archived FROM categories")}
    return accs, cats


def _convert(row: dict, accs: dict, cats: dict, new_cats: set) -> tuple[dict, list[str]]:
    """CSV row -> payload for transactions.create_in, plus the errors found."""
    errors: list[str] = []
    kind = KINDS.get(row.get("tipo", "").lower())
    if not kind:
        errors.append(f"tipo '{row.get('tipo')}' non valido (spesa, entrata, trasferimento)")
    try:
        day = money.parse_date(row.get("data")).isoformat()
    except ValidationError:
        day = None
        errors.append(f"data '{row.get('data')}' non valida")

    def account(col):
        name = row.get(col, "")
        if not name:
            errors.append(f"{col.replace('_', ' ')} mancante")
            return None
        acc = accs.get(name.lower())
        if not acc:
            errors.append(f"conto '{name}' inesistente")
        return acc

    payload: dict = {"kind": kind, "date": day, "description": row.get("descrizione", "")}
    if kind == "expense":
        acc = account("conto_origine")
        payload.update(account_id=acc and acc["id"], amount=row.get("importo"))
    elif kind == "income":
        acc = account("conto_destinazione")
        payload.update(account_id=acc and acc["id"], amount=row.get("importo"))
    elif kind == "transfer":
        src, dst = account("conto_origine"), account("conto_destinazione")
        received = row.get("importo_destinazione") or row.get("importo")
        if src and dst and src["currency"] != dst["currency"] and not row.get("importo_destinazione"):
            errors.append(f"valute diverse ({src['currency']} → {dst['currency']}): indica importo_destinazione")
        payload.update(from_account_id=src and src["id"], to_account_id=dst and dst["id"],
                       sent_amount=row.get("importo"), amount=received)
    cat_name = row.get("categoria", "")
    if kind and cat_name:
        cat = cats.get((cat_name.lower(), NATURE[kind]))
        if cat:
            payload["category_id"] = cat["id"]
        else:
            new_cats.add((cat_name, NATURE[kind]))
            payload["_new_category"] = (cat_name, NATURE[kind])
    elif kind in ("expense", "income"):
        errors.append("categoria mancante")
    return payload, errors


def _duplicate_key(day, account_id, amount_minor, description) -> tuple:
    return (day, account_id, amount_minor, " ".join((description or "").lower().split()))


def _existing_keys(conn: sqlite3.Connection) -> set:
    keys = set()
    for r in conn.execute("SELECT date, from_account_id, to_account_id, from_amount, to_amount, kind, description"
                          " FROM transactions WHERE kind IN ('expense', 'income', 'transfer')"):
        side = "to" if r["kind"] == "income" else "from"
        keys.add(_duplicate_key(r["date"], r[f"{side}_account_id"], r[f"{side}_amount"], r["description"]))
    return keys


def _iso_or_none(text) -> str | None:
    try:
        return money.parse_date(text).isoformat()
    except ValidationError:
        return None


def _entry_id(row: dict) -> tuple[str | None, str | None]:
    """(normalized UUID, error) of a smartphone row."""
    raw = row.get("id", "")
    if not raw:
        return None, "id mancante"
    try:
        return str(uuid.UUID(raw)), None
    except ValueError:
        return None, f"id '{raw[:40]}' non valido"


def _process(conn: sqlite3.Connection, text: str, create_categories: bool, track_ids: bool = False) -> dict:
    """Validate every row inside the given (to be committed or rolled back) transaction."""
    rows = _rows(text)
    imported_ids = {r[0] for r in conn.execute("SELECT id FROM mobile_imported_ids")} if track_ids else set()
    skipped = []
    if track_ids:
        kept = []
        for r in rows:
            rid, err = _entry_id(r)
            r["_id"], r["_id_error"] = rid, err
            if rid and rid in imported_ids:
                skipped.append(r)
            else:
                kept.append(r)
                if rid:
                    imported_ids.add(rid)  # a repeated id later in the same file is skipped too
        rows = kept
    accs, cats = _lookup(conn)
    new_cats: set = set()
    converted = [(_convert(r, accs, cats, new_cats), r) for r in rows]
    if create_categories:
        for name, nature in sorted(new_cats):
            cid = conn.execute("INSERT INTO categories (name, nature) VALUES (?, ?)", (name, nature)).lastrowid
            cats[(name.lower(), nature)] = {"id": cid, "name": name, "nature": nature, "archived": 0}
    existing = _existing_keys(conn)
    seen: set = set()
    report = []
    for (payload, errors), raw in converted:
        warnings = []
        if raw.get("_id_error"):
            errors.append(raw["_id_error"])
        new_cat = payload.pop("_new_category", None)
        if new_cat:
            if create_categories:
                payload["category_id"] = cats[(new_cat[0].lower(), new_cat[1])]["id"]
            else:
                errors.append(f"categoria '{new_cat[0]}' sconosciuta")
        tx_id = None
        if not errors:
            conn.execute("SAVEPOINT row")
            try:
                tx_id, _ = transactions.create_in(conn, payload)
                conn.execute("RELEASE row")
            except ValidationError as e:
                conn.execute("ROLLBACK TO row")
                conn.execute("RELEASE row")
                errors.append(str(e).rstrip(".").lower() if str(e) else "riga non valida")
        if tx_id is not None:
            t = conn.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
            side = "to" if t["kind"] == "income" else "from"
            key = _duplicate_key(t["date"], t[f"{side}_account_id"], t[f"{side}_amount"], t["description"])
            if key in existing:
                warnings.append("possibile duplicato di un'operazione già presente")
            elif key in seen:
                warnings.append("possibile duplicato di un'altra riga del file")
            seen.add(key)
            if raw.get("_id"):
                conn.execute("INSERT INTO mobile_imported_ids (id, imported_at) VALUES (?, ?)", (raw["_id"], now_iso()))
        report.append({
            "line": raw["_line"], "date": payload.get("date"), "kind": payload.get("kind"),
            "description": raw.get("descrizione", ""), "amount": raw.get("importo", ""),
            "account": raw.get("conto_origine") or raw.get("conto_destinazione"),
            "to_account": raw.get("conto_destinazione") if payload.get("kind") == "transfer" else None,
            "category": raw.get("categoria", ""), "errors": errors, "warnings": warnings,
        })
    for raw in skipped:
        report.append({
            "line": raw["_line"], "date": _iso_or_none(raw.get("data")), "kind": KINDS.get(raw.get("tipo", "").lower()),
            "description": raw.get("descrizione", ""), "amount": raw.get("importo", ""),
            "account": raw.get("conto_origine") or raw.get("conto_destinazione"),
            "to_account": raw.get("conto_destinazione") if raw.get("conto_origine") and raw.get("conto_destinazione") else None,
            "category": raw.get("categoria", ""), "errors": [], "warnings": [], "skipped": "già importata",
        })
    report.sort(key=lambda r: r["line"])
    return {
        "rows": report,
        "total": len(report),
        "skipped": len(skipped),
        "valid": sum(1 for r in report if not r["errors"] and not r.get("skipped")),
        "errors": sum(1 for r in report if r["errors"]),
        "duplicates": sum(1 for r in report if r["warnings"]),
        "new_categories": [{"name": n, "nature": k} for n, k in sorted(new_cats)],
    }


class _Rollback(Exception):
    pass


def preview(db: Database, text: str, create_categories: bool = False, track_ids: bool = False) -> dict:
    """Dry run: everything is validated (and inserted) inside a transaction that is
    always rolled back."""
    result: dict = {}
    try:
        with db.transaction() as conn:
            result = _process(conn, text, create_categories, track_ids)
            raise _Rollback
    except _Rollback:
        pass
    return result


def import_csv(db: Database, text: str, create_categories: bool = False, track_ids: bool = False) -> dict:
    """All rows or none: any invalid row aborts the whole import."""
    with db.transaction() as conn:
        result = _process(conn, text, create_categories, track_ids)
        if result["errors"]:
            bad = next(r for r in result["rows"] if r["errors"])
            raise ValidationError(
                f"{result['errors']} righe con errori (riga {bad['line']}: {bad['errors'][0]}). Nessuna operazione importata."
            )
    result["imported"] = result["valid"]
    return result


# ------------------------------------------------------------------- exports


def _csv(header: list[str], rows: list[list]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(header)
    w.writerows(rows)
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM: Excel reads it as UTF-8


def _it_num(value: str | None) -> str:
    return "" if value is None else str(value).replace(".", ",")


def _it_date(iso: str | None) -> str:
    if not iso:
        return ""
    y, m, d = iso.split("-")
    return f"{d}/{m}/{y}"


_KIND_IT = {"expense": "spesa", "income": "entrata", "transfer": "trasferimento", "interest": "interessi",
            "fee": "commissione", "buy": "acquisto", "sell": "vendita"}


def export_operations(db: Database, fmt: str, filters: dict) -> tuple[bytes, str]:
    items = []
    offset = 0
    flt = {k: v for k, v in filters.items() if k in ("account", "from", "to") and v}
    flt["with_linked_fees"] = True
    while True:
        page = transactions.list_transactions(db, flt, limit=1000, offset=offset)
        items += page["items"]
        if not page["has_more"]:
            break
        offset += 1000
    items.reverse()  # oldest first
    if fmt == "json":
        return _json([{k: v for k, v in t.items() if k not in ("editable",)} for t in items])
    rows = []
    for t in items:
        transfer = t["kind"] == "transfer"
        rows.append([
            _it_date(t["date"]), _KIND_IT[t["kind"]],
            t["from_account_name"] or "", t["to_account_name"] or "",
            _it_num(t["from_amount"] if transfer else t["amount"]),
            _it_num(t["to_amount"]) if transfer and t["from_currency"] != t["to_currency"] else "",
            t["category_name"] or "", t["description"],
            t["from_currency"] if transfer else t["currency"], _it_num(t["eur"]),
        ])
    return _csv(COLUMNS + ["valuta", "eur"], rows), "csv"


def export_accounts(db: Database, fmt: str) -> tuple[bytes, str]:
    from . import accounts

    items = accounts.list_accounts(db)
    if fmt == "json":
        return _json(items)
    return _csv(["nome", "banca", "valuta", "tipo", "apertura", "saldo_iniziale", "saldo", "archiviato", "note"], [
        [a["name"], a["bank"], a["currency"], a["type_name"], _it_date(a["opened_on"]), _it_num(a["opening_balance"]),
         _it_num(a["balance"]), "sì" if a["archived"] else "no", a["notes"]] for a in items]), "csv"


def export_categories(db: Database, fmt: str) -> tuple[bytes, str]:
    from . import categories

    items = categories.list_categories(db)
    if fmt == "json":
        return _json(items)
    nat = {"expense": "spesa", "income": "entrata", "transfer": "trasferimento"}
    return _csv(["nome", "natura", "archiviata", "operazioni"], [
        [c["name"], nat[c["nature"]], "sì" if c["archived"] else "no", c["used"]] for c in items]), "csv"


def export_investments(db: Database, fmt: str) -> tuple[bytes, str]:
    data = []
    for acc in investments.list_accounts(db):
        p = investments.portfolio(db, acc["id"])
        for a in p["assets"]:
            a.pop("series", None)
        data.append(p)
    if fmt == "json":
        for p in data:
            p.pop("series", None)
        return _json(data)
    rows = []
    for p in data:
        for a in p["assets"]:
            rows.append([p["account"]["name"], p["account"]["currency"], a["ticker"], a["name"], _it_num(a.get("shares")),
                         _it_num(a.get("invested")), _it_num(a.get("value")), _it_num(a.get("gain")),
                         _it_num(a.get("realized")),
                         "" if a.get("return_pct") is None else f"{a['return_pct']:.2f}".replace(".", ","),
                         "" if a.get("annualized_pct") is None else f"{a['annualized_pct']:.2f}".replace(".", ","),
                         _it_date(a.get("last_date")), a.get("error") or ""])
    return _csv(["conto", "valuta", "ticker", "nome", "quote", "investito", "valore", "guadagno", "realizzato",
                 "rendimento_pct", "xirr_pct", "ultimo_prezzo_del", "errore"], rows), "csv"


def export_monthly(db: Database, fmt: str, filters: dict) -> tuple[bytes, str]:
    today = date.today()
    start = filters.get("from") or f"{today.year}-01-01"
    end = filters.get("to") or today.isoformat()
    s, e = money.parse_date(start), money.parse_date(end)
    months = []
    m = s.replace(day=1)
    while m <= e:
        nxt = analytics._month_add(m, 1)
        last = min(e, date.fromordinal(nxt.toordinal() - 1))
        rep = analytics.account_report(db, max(s, m).isoformat(), last.isoformat())
        months.append({"month": m.strftime("%Y-%m"), **rep})
        m = nxt
    if fmt == "json":
        return _json(months)
    rows = []
    for mo in months:
        for a in mo["accounts"]:
            rows.append([mo["month"], a["name"], a["currency"]] + [
                _it_num(a[c]) for c in ("income", "expenses", "transfers", "invested")] + [
                _it_num(a[f"{c}_eur"]) for c in ("income", "expenses", "transfers", "invested")])
    return _csv(["mese", "conto", "valuta", "entrate", "uscite", "trasferimenti", "investito", "entrate_eur",
                 "uscite_eur", "trasferimenti_eur", "investito_eur"], rows), "csv"


def _json(data) -> tuple[bytes, str]:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str).encode("utf-8"), "json"


EXPORTS = {
    "operazioni": lambda db, fmt, f: export_operations(db, fmt, f),
    "conti": lambda db, fmt, f: export_accounts(db, fmt),
    "categorie": lambda db, fmt, f: export_categories(db, fmt),
    "investimenti": lambda db, fmt, f: export_investments(db, fmt),
    "report-mensile": lambda db, fmt, f: export_monthly(db, fmt, f),
}


def export(db: Database, what: str, fmt: str, filters: dict) -> tuple[bytes, str, str]:
    if what not in EXPORTS:
        raise ValidationError("Export non valido.")
    if fmt not in ("csv", "json"):
        raise ValidationError("Formato non valido (csv o json).")
    body, ext = EXPORTS[what](db, fmt, filters)
    return body, f"myWealth_{what}_{date.today().isoformat()}.{ext}", ext

