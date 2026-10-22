"""Operations: expenses, income, transfers (with a linked fee), plus the kinds the app
creates itself (interest, fees, asset buys and sells).

Every operation stores, for each side, the EUR rate of its date (snapshot): historical
reports use it, so a later change of the exchange rate never rewrites the past.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal

from . import accounts, categories, fx, money
from .db import Database, now_iso
from .errors import ConflictError, NotFoundError, ValidationError

USER_KINDS = ("expense", "income", "transfer")
KIND_NAMES = {
    "expense": "Spesa",
    "income": "Entrata",
    "transfer": "Trasferimento",
    "interest": "Interessi",
    "fee": "Commissione",
    "buy": "Acquisto",
    "sell": "Vendita",
}
# side whose amount is "the" amount of the operation (shown in lists, used in reports)
MAIN_SIDE = {"expense": "from", "fee": "from", "buy": "from", "income": "to", "interest": "to", "sell": "to",
             "transfer": "to"}
MAX_DESCRIPTION = 200
DEFAULT_PAGE = 30


# ------------------------------------------------------------------- helpers


def _description(value) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > MAX_DESCRIPTION:
        raise ValidationError(f"Descrizione troppo lunga (max {MAX_DESCRIPTION} caratteri).")
    return text


def _date(value, field: str = "data") -> str:
    d = money.parse_date(value or date.today().isoformat(), field)
    if d > date.today():
        raise ValidationError("La data non può essere nel futuro.")
    return d.isoformat()


def _account(conn: sqlite3.Connection, account_id, day: str, keep_id: int | None = None,
             label: str = "conto") -> sqlite3.Row:
    """An account usable for an operation on `day`; an archived one only if already in use."""
    if account_id in (None, ""):
        raise ValidationError(f"Scegli il {label}.")
    acc = accounts.account_row(conn, account_id)
    if acc["archived"] and acc["id"] != keep_id:
        raise ValidationError(f"Il conto '{acc['name']}' è archiviato.")
    if day < acc["opened_on"]:
        raise ValidationError(
            f"Il conto '{acc['name']}' è stato aperto il {_it(acc['opened_on'])}: la data non può essere precedente."
        )
    return acc


def _it(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}/{m}/{y}"


def _rates(conn: sqlite3.Connection, row: dict) -> None:
    """Fill the EUR snapshot rates of both sides from the stored exchange rates."""
    for side in ("from", "to"):
        acc_id = row.get(f"{side}_account_id")
        if acc_id is None:
            row[f"{side}_rate"] = row[f"{side}_rate_date"] = None
            continue
        cur = conn.execute("SELECT currency FROM accounts WHERE id = ?", (acc_id,)).fetchone()[0]
        row[f"{side}_rate"], row[f"{side}_rate_date"] = fx.snapshot(conn, cur, row["date"])


_COLUMNS = ("kind", "date", "from_account_id", "to_account_id", "from_amount", "to_amount", "from_rate",
            "from_rate_date", "to_rate", "to_rate_date", "category_id", "description", "linked_id", "auto")


def write(conn: sqlite3.Connection, row: dict, tx_id: int | None = None) -> int:
    """Insert or update a transaction row (low level: callers validate). Returns its id."""
    row = {"from_account_id": None, "to_account_id": None, "from_amount": None, "to_amount": None,
           "category_id": None, "description": "", "linked_id": None, "auto": 0, **row}
    _rates(conn, row)
    now = now_iso()
    values = {k: row[k] for k in _COLUMNS}
    if tx_id is None:
        values.update(created_at=now, updated_at=now)
        cols = ", ".join(values)
        return conn.execute(
            f"INSERT INTO transactions ({cols}) VALUES ({', '.join('?' * len(values))})", tuple(values.values())
        ).lastrowid
    values["updated_at"] = now
    sets = ", ".join(f"{k} = ?" for k in values)
    conn.execute(f"UPDATE transactions SET {sets} WHERE id = ?", (*values.values(), tx_id))
    return tx_id


def _row(conn: sqlite3.Connection, tx_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    if not row:
        raise NotFoundError("Operazione non trovata.")
    return row


# ------------------------------------------------------------- user operations


def _build(conn: sqlite3.Connection, data: dict, current: sqlite3.Row | None) -> tuple[dict, dict | None]:
    """Validate a user payload -> (transaction row, fee spec or None)."""
    kind = current["kind"] if current else data.get("kind")
    keep = lambda side: current[f"{side}_account_id"] if current else None  # noqa: E731
    day = _date(data.get("date"))
    desc = _description(data.get("description"))
    fee = None

    if kind in ("expense", "income", "interest"):
        side = "from" if kind == "expense" else "to"
        acc = _account(conn, data.get("account_id"), day, keep(side))
        amount = money.parse_amount(data.get("amount"), acc["currency"])
        if kind == "interest":
            cat = categories.system_category(conn, "interest")
        else:
            cat = categories.check_category(conn, data.get("category_id"), categories.NATURE_OF_KIND[kind],
                                            current["category_id"] if current else None)
        row = {"kind": kind, "date": day, f"{side}_account_id": acc["id"], f"{side}_amount": amount,
               "category_id": cat, "description": desc}
    elif kind == "transfer":
        src = _account(conn, data.get("from_account_id"), day, keep("from"), "conto di origine")
        dst = _account(conn, data.get("to_account_id"), day, keep("to"), "conto di destinazione")
        if src["id"] == dst["id"]:
            raise ValidationError("Il conto di destinazione deve essere diverso da quello di origine.")
        received = money.parse_amount(data.get("amount"), dst["currency"], "importo ricevuto")
        if src["currency"] == dst["currency"]:
            sent = received
        else:
            sent = money.parse_amount(data.get("sent_amount"), src["currency"], "importo inviato")
        cat_raw = data.get("category_id")
        if cat_raw in (None, ""):
            cat = categories.system_category(conn, "transfer")
        else:
            cat = categories.check_category(conn, cat_raw, "transfer", current["category_id"] if current else None)
        row = {"kind": kind, "date": day, "from_account_id": src["id"], "to_account_id": dst["id"],
               "from_amount": sent, "to_amount": received, "category_id": cat,
               "description": desc or f"Trasferimento da {src['name']} a {dst['name']}"}
        if data.get("fee_amount") not in (None, ""):
            side = data.get("fee_side", "from")
            if side not in ("from", "to"):
                raise ValidationError("Scegli il conto da cui addebitare la commissione.")
            fee_acc = src if side == "from" else dst
            fee = {"account": fee_acc,
                   "amount": money.parse_amount(data["fee_amount"], fee_acc["currency"], "commissione")}
    elif kind == "fee":
        acc = _account(conn, data.get("account_id"), day, keep("from"))
        amount = money.parse_amount(data.get("amount"), acc["currency"])
        cat = categories.check_category(conn, data.get("category_id") or current["category_id"], "expense",
                                        current["category_id"])
        row = {"kind": kind, "date": day, "from_account_id": acc["id"], "from_amount": amount,
               "category_id": cat, "description": desc, "linked_id": current["linked_id"]}
    else:
        raise ValidationError("Tipo di operazione non valido.")
    return row, fee


def _save_fee(conn: sqlite3.Connection, transfer_id: int, transfer: dict, fee: dict | None) -> None:
    existing = conn.execute(
        "SELECT id FROM transactions WHERE linked_id = ? AND kind = 'fee'", (transfer_id,)
    ).fetchone()
    if fee is None:
        if existing:
            conn.execute("DELETE FROM transactions WHERE id = ?", (existing[0],))
        return
    row = {"kind": "fee", "date": transfer["date"], "from_account_id": fee["account"]["id"],
           "from_amount": fee["amount"], "category_id": categories.system_category(conn, "fees"),
           "description": f"Commissione: {transfer['description']}"[:MAX_DESCRIPTION],
           "linked_id": transfer_id, "auto": 1}
    write(conn, row, existing[0] if existing else None)


def _warnings(conn: sqlite3.Connection, account_ids) -> list[str]:
    out = []
    bals = accounts.balances(conn)
    for acc_id in dict.fromkeys(a for a in account_ids if a is not None):
        if bals.get(acc_id, 0) < 0:
            acc = conn.execute("SELECT name, currency FROM accounts WHERE id = ?", (acc_id,)).fetchone()
            out.append(f"Il saldo di '{acc['name']}' è negativo: {money.fmt(bals[acc_id], acc['currency'])} "
                       f"{acc['currency']}.")
    return out


def create(db: Database, data: dict) -> dict:
    if data.get("kind") not in USER_KINDS:
        raise ValidationError("Tipo di operazione non valido.")
    with db.transaction() as conn:
        row, fee = _build(conn, data, None)
        tx_id = write(conn, row)
        if row["kind"] == "transfer":
            _save_fee(conn, tx_id, row, fee)
        out = _get(conn, tx_id)
        out["warnings"] = _warnings(conn, [row.get("from_account_id"), row.get("to_account_id"),
                                           fee and fee["account"]["id"]])
    return out


def update(db: Database, tx_id: int, data: dict) -> dict:
    with db.transaction() as conn:
        current = _row(conn, tx_id)
        if current["kind"] in ("buy", "sell"):
            raise ConflictError("Acquisti e vendite si modificano dalla scheda Investimenti.")
        if current["kind"] == "fee" and current["linked_id"] is not None:
            parent = _row(conn, current["linked_id"])
            if parent["kind"] == "transfer":
                raise ConflictError("Questa commissione è collegata a un trasferimento: modifica il trasferimento.")
            raise ConflictError("Questa commissione è collegata a un'operazione sugli asset: modificala dagli Investimenti.")
        row, fee = _build(conn, data, current)
        row["auto"] = current["auto"]
        write(conn, row, tx_id)
        if row["kind"] == "transfer":
            _save_fee(conn, tx_id, row, fee)
        out = _get(conn, tx_id)
        touched = [current["from_account_id"], current["to_account_id"], row.get("from_account_id"),
                   row.get("to_account_id"), fee and fee["account"]["id"]]
        out["warnings"] = _warnings(conn, touched)
    return out


def delete(db: Database, tx_id: int) -> None:
    with db.transaction() as conn:
        current = _row(conn, tx_id)
        if current["kind"] in ("buy", "sell"):
            raise ConflictError("Acquisti e vendite si eliminano dalla scheda Investimenti.")
        if current["kind"] == "fee" and current["linked_id"] is not None:
            parent = _row(conn, current["linked_id"])
            if parent["kind"] in ("buy", "sell"):
                raise ConflictError("Questa commissione è collegata a un'operazione sugli asset: modificala dagli Investimenti.")
        conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))  # a linked fee goes with it (cascade)


# ---------------------------------------------------------------------- reading

_SELECT = """
    SELECT t.*,
           fa.name AS from_name, fa.currency AS from_currency,
           ta.name AS to_name, ta.currency AS to_currency,
           c.name AS category_name,
           fee.id AS fee_id, fee.from_account_id AS fee_account_id, fee.from_amount AS fee_amount
    FROM transactions t
    LEFT JOIN accounts fa ON fa.id = t.from_account_id
    LEFT JOIN accounts ta ON ta.id = t.to_account_id
    LEFT JOIN categories c ON c.id = t.category_id
    LEFT JOIN transactions fee ON fee.linked_id = t.id AND fee.kind = 'fee' AND t.kind = 'transfer'
"""


def eur_value(minor: int | None, currency: str | None, rate: str | None) -> Decimal | None:
    if minor is None or rate is None:
        return None
    return money.from_minor(minor, currency) * Decimal(rate)


def _dict(r: sqlite3.Row) -> dict:
    main = MAIN_SIDE[r["kind"]]
    out = {
        "id": r["id"],
        "kind": r["kind"],
        "kind_name": KIND_NAMES[r["kind"]],
        "date": r["date"],
        "description": r["description"],
        "category_id": r["category_id"],
        "category_name": r["category_name"],
        "linked_id": r["linked_id"],
        "auto": bool(r["auto"]),
        "editable": r["kind"] not in ("buy", "sell") and not (r["kind"] == "fee" and r["linked_id"] is not None),
    }
    for side in ("from", "to"):
        cur = r[f"{side}_currency"]
        out[f"{side}_account_id"] = r[f"{side}_account_id"]
        out[f"{side}_account_name"] = r[f"{side}_name"]
        out[f"{side}_currency"] = cur
        out[f"{side}_amount"] = money.fmt(r[f"{side}_amount"], cur) if cur else None
        out[f"{side}_rate"] = r[f"{side}_rate"]
        out[f"{side}_rate_date"] = r[f"{side}_rate_date"]
        out[f"{side}_eur"] = money.fmt_decimal(eur_value(r[f"{side}_amount"], cur, r[f"{side}_rate"]))
    out["amount"] = out[f"{main}_amount"]
    out["currency"] = out[f"{main}_currency"]
    out["eur"] = out[f"{main}_eur"]
    out["account_id"] = out[f"{main}_account_id"]
    out["account_name"] = out[f"{main}_account_name"]
    if r["fee_id"] is not None:
        side = "from" if r["fee_account_id"] == r["from_account_id"] else "to"
        out["fee"] = {"id": r["fee_id"], "side": side, "amount": money.fmt(r["fee_amount"], r[f"{side}_currency"]),
                      "currency": r[f"{side}_currency"]}
    else:
        out["fee"] = None
    return out


def _get(conn: sqlite3.Connection, tx_id: int) -> dict:
    row = conn.execute(f"{_SELECT} WHERE t.id = ?", (tx_id,)).fetchone()
    if not row:
        raise NotFoundError("Operazione non trovata.")
    return _dict(row)


def get(db: Database, tx_id: int) -> dict:
    with db.connect() as conn:
        return _get(conn, tx_id)


def list_transactions(db: Database, filters: dict | None = None, limit: int = DEFAULT_PAGE,
                      offset: int = 0) -> dict:
    """Newest first. Filters: account, category, kind, from, to (dates), q (text search)."""
    where, args = _filters(filters or {})
    limit = max(1, min(int(limit), 1000))
    with db.connect() as conn:
        rows = conn.execute(
            f"{_SELECT} {where} ORDER BY t.date DESC, t.id DESC LIMIT ? OFFSET ?", (*args, limit + 1, max(0, offset))
        ).fetchall()
        total = conn.execute(f"SELECT COUNT(*) FROM transactions t {where}", args).fetchone()[0]
    return {"items": [_dict(r) for r in rows[:limit]], "has_more": len(rows) > limit, "total": total}


def _int(value, what: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"Filtro {what} non valido.") from None


def _filters(f: dict) -> tuple[str, tuple]:
    conds: list[str] = []
    args: list = []
    if f.get("account"):
        conds.append("(t.from_account_id = ? OR t.to_account_id = ?)")
        args += [_int(f["account"], "conto")] * 2
    if f.get("category"):
        conds.append("t.category_id = ?")
        args.append(_int(f["category"], "categoria"))
    if f.get("kind"):
        kinds = [k for k in str(f["kind"]).split(",") if k in KIND_NAMES]
        if not kinds:
            raise ValidationError("Tipo di operazione non valido.")
        conds.append(f"t.kind IN ({', '.join('?' * len(kinds))})")
        args += kinds
    if f.get("from"):
        conds.append("t.date >= ?")
        args.append(money.parse_date(f["from"]).isoformat())
    if f.get("to"):
        conds.append("t.date <= ?")
        args.append(money.parse_date(f["to"]).isoformat())
    if f.get("q"):
        conds.append("t.description LIKE ? ESCAPE '\\'")
        q = str(f["q"]).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        args.append(f"%{q}%")
    # a transfer's fee is shown inside the transfer row unless fees are asked for explicitly
    if not f.get("kind") and not f.get("with_linked_fees"):
        conds.append("NOT (t.kind = 'fee' AND t.linked_id IS NOT NULL AND"
                     " (SELECT kind FROM transactions p WHERE p.id = t.linked_id) = 'transfer')")
    return ("WHERE " + " AND ".join(conds)) if conds else "", tuple(args)
