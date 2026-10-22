"""Accounts and account types.

A balance is never stored: it is always the opening balance plus the movements, so
editing or deleting an operation can't leave it out of sync.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from . import money
from .db import Database, now_iso
from .errors import ConflictError, NotFoundError, ValidationError

BEHAVIORS = ("standard", "savings", "investment")
MAX_NAME = 80
MAX_NOTES = 1000


# ------------------------------------------------------------------ account types


def list_types(db: Database) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT t.*, (SELECT COUNT(*) FROM accounts a WHERE a.type_id = t.id) AS used"
            " FROM account_types t ORDER BY t.builtin DESC, t.id"
        ).fetchall()
    return [_type_dict(r) for r in rows]


def _type_dict(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "behavior": r["behavior"],
        "builtin": bool(r["builtin"]),
        "archived": bool(r["archived"]),
        "used": r["used"],
    }


def _clean_name(value, field: str = "nome", max_len: int = MAX_NAME) -> str:
    name = " ".join(str(value or "").split())
    if not name:
        raise ValidationError(f"Il {field} è obbligatorio.")
    if len(name) > max_len:
        raise ValidationError(f"Il {field} è troppo lungo (max {max_len} caratteri).")
    return name


def create_type(db: Database, data: dict) -> dict:
    name = _clean_name(data.get("name"))
    behavior = data.get("behavior", "standard")
    if behavior not in BEHAVIORS:
        raise ValidationError("Comportamento non valido.")
    with db.transaction() as conn:
        try:
            cur = conn.execute("INSERT INTO account_types (name, behavior) VALUES (?, ?)", (name, behavior))
        except sqlite3.IntegrityError:
            raise ConflictError(f"Esiste già un tipo di conto '{name}'.") from None
        type_id = cur.lastrowid
    return get_type(db, type_id)


def get_type(db: Database, type_id: int) -> dict:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT t.*, (SELECT COUNT(*) FROM accounts a WHERE a.type_id = t.id) AS used"
            " FROM account_types t WHERE t.id = ?",
            (type_id,),
        ).fetchone()
    if not row:
        raise NotFoundError("Tipo di conto non trovato.")
    return _type_dict(row)


def update_type(db: Database, type_id: int, data: dict) -> dict:
    current = get_type(db, type_id)
    fields: dict = {}
    if "name" in data:
        fields["name"] = _clean_name(data["name"])
    if "archived" in data:
        fields["archived"] = 1 if data["archived"] else 0
    if "behavior" in data and data["behavior"] != current["behavior"]:
        # The behavior decides which features an account has (interest, assets): changing
        # it under existing accounts would orphan their data.
        if current["builtin"] or current["used"]:
            raise ConflictError("Il comportamento di un tipo già usato non si può cambiare.")
        if data["behavior"] not in BEHAVIORS:
            raise ValidationError("Comportamento non valido.")
        fields["behavior"] = data["behavior"]
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        with db.transaction() as conn:
            try:
                conn.execute(f"UPDATE account_types SET {sets} WHERE id = ?", (*fields.values(), type_id))
            except sqlite3.IntegrityError:
                raise ConflictError(f"Esiste già un tipo di conto '{fields['name']}'.") from None
    return get_type(db, type_id)


def delete_type(db: Database, type_id: int) -> None:
    t = get_type(db, type_id)
    if t["builtin"]:
        raise ConflictError("I tipi predefiniti non si possono eliminare.")
    if t["used"]:
        raise ConflictError("Tipo usato da almeno un conto: archivialo invece di eliminarlo.")
    with db.transaction() as conn:
        conn.execute("DELETE FROM account_types WHERE id = ?", (type_id,))


# ----------------------------------------------------------------------- accounts

_ACCOUNT_SQL = """
    SELECT a.*, t.name AS type_name, t.behavior
    FROM accounts a JOIN account_types t ON t.id = a.type_id
"""


def movement_count(conn: sqlite3.Connection, account_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE from_account_id = ? OR to_account_id = ?",
        (account_id, account_id),
    ).fetchone()[0]


def balances(conn: sqlite3.Connection, as_of: str | None = None) -> dict[int, int]:
    """Balance in minor units for every account: opening balance + incoming - outgoing.

    With `as_of` (YYYY-MM-DD) only operations up to that day (included) are counted.
    """
    cond, args = ("AND date <= ?", (as_of,)) if as_of else ("", ())
    result = {r[0]: r[1] for r in conn.execute("SELECT id, opening_balance FROM accounts")}
    for acc, amount in conn.execute(
        f"SELECT to_account_id, SUM(to_amount) FROM transactions"
        f" WHERE to_account_id IS NOT NULL {cond} GROUP BY to_account_id",
        args,
    ):
        result[acc] = result.get(acc, 0) + amount
    for acc, amount in conn.execute(
        f"SELECT from_account_id, SUM(from_amount) FROM transactions"
        f" WHERE from_account_id IS NOT NULL {cond} GROUP BY from_account_id",
        args,
    ):
        result[acc] = result.get(acc, 0) - amount
    return result


def balance(conn: sqlite3.Connection, account_id: int, as_of: str | None = None) -> int:
    return balances(conn, as_of).get(account_id, 0)


def _account_dict(r: sqlite3.Row, bal: int, movements: int) -> dict:
    cur = r["currency"]
    return {
        "id": r["id"],
        "name": r["name"],
        "bank": r["bank"],
        "currency": cur,
        "opened_on": r["opened_on"],
        "opening_balance": money.fmt(r["opening_balance"], cur),
        "type_id": r["type_id"],
        "type_name": r["type_name"],
        "behavior": r["behavior"],
        "archived": bool(r["archived"]),
        "notes": r["notes"],
        "balance": money.fmt(bal, cur),
        "balance_minor": bal,
        "movements": movements,
    }


def list_accounts(db: Database, include_archived: bool = True) -> list[dict]:
    from .savings import current_rates

    with db.connect() as conn:
        where = "" if include_archived else "WHERE a.archived = 0"
        rows = conn.execute(f"{_ACCOUNT_SQL} {where} ORDER BY a.archived, a.name COLLATE NOCASE").fetchall()
        bals = balances(conn)
        counts = _movement_counts(conn)
        rates = current_rates(conn)
    out = [_account_dict(r, bals.get(r["id"], 0), counts.get(r["id"], 0)) for r in rows]
    for a in out:
        a["annual_rate"] = rates.get(a["id"]) if a["behavior"] == "savings" else None
    return out


def _movement_counts(conn: sqlite3.Connection) -> dict[int, int]:
    counts: dict[int, int] = {}
    for col in ("from_account_id", "to_account_id"):
        for acc, n in conn.execute(
            f"SELECT {col}, COUNT(*) FROM transactions WHERE {col} IS NOT NULL GROUP BY {col}"
        ):
            counts[acc] = counts.get(acc, 0) + n
    return counts


def get_account(db: Database, account_id: int) -> dict:
    with db.connect() as conn:
        return _get_account(conn, account_id)


def _get_account(conn: sqlite3.Connection, account_id: int) -> dict:
    row = conn.execute(f"{_ACCOUNT_SQL} WHERE a.id = ?", (account_id,)).fetchone()
    if not row:
        raise NotFoundError("Conto non trovato.")
    return _account_dict(row, balance(conn, account_id), movement_count(conn, account_id))


def account_row(conn: sqlite3.Connection, account_id) -> sqlite3.Row:
    try:
        account_id = int(account_id)
    except (TypeError, ValueError):
        raise ValidationError("Conto non valido.") from None
    row = conn.execute(f"{_ACCOUNT_SQL} WHERE a.id = ?", (account_id,)).fetchone()
    if not row:
        raise ValidationError("Conto non trovato.")
    return row


def _validate(conn: sqlite3.Connection, data: dict, current: dict | None) -> dict:
    """Return the clean column values for an insert (current=None) or an update."""
    out: dict = {}
    if current is None or "name" in data:
        out["name"] = _clean_name(data.get("name"))
    if current is None or "bank" in data:
        out["bank"] = " ".join(str(data.get("bank") or "").split())[:MAX_NAME]
    if current is None or "notes" in data:
        notes = str(data.get("notes") or "").strip()
        if len(notes) > MAX_NOTES:
            raise ValidationError(f"Note troppo lunghe (max {MAX_NOTES} caratteri).")
        out["notes"] = notes
    if current is None or "currency" in data:
        out["currency"] = money.check_currency(data.get("currency"))
    currency = out.get("currency") or current["currency"]
    if current is None or "opened_on" in data:
        opened = money.parse_date(data.get("opened_on") or date.today().isoformat(), "data di apertura")
        if opened > date.today():
            raise ValidationError("La data di apertura non può essere nel futuro.")
        out["opened_on"] = opened.isoformat()
    if current is None or "opening_balance" in data or "currency" in data:
        raw = data.get("opening_balance", current["opening_balance"] if current else None)
        out["opening_balance"] = (
            0 if raw in (None, "") else
            money.parse_amount(raw, currency, "saldo iniziale", allow_negative=True, allow_zero=True)
        )
    if current is None or "type_id" in data:
        try:
            type_id = int(data.get("type_id"))
        except (TypeError, ValueError):
            raise ValidationError("Scegli il tipo di conto.") from None
        t = conn.execute("SELECT id, archived FROM account_types WHERE id = ?", (type_id,)).fetchone()
        if not t:
            raise ValidationError("Tipo di conto non trovato.")
        if t["archived"] and (current is None or current["type_id"] != type_id):
            raise ValidationError("Il tipo di conto è archiviato.")
        out["type_id"] = type_id
    if current is not None and "archived" in data:
        out["archived"] = 1 if data["archived"] else 0
    return out


def create_account(db: Database, data: dict) -> dict:
    with db.transaction() as conn:
        values = _validate(conn, data, None)
        now = now_iso()
        values.update(created_at=now, updated_at=now)
        cols = ", ".join(values)
        try:
            cur = conn.execute(
                f"INSERT INTO accounts ({cols}) VALUES ({', '.join('?' * len(values))})",
                tuple(values.values()),
            )
        except sqlite3.IntegrityError:
            raise ConflictError(f"Esiste già un conto chiamato '{values['name']}'.") from None
        return _get_account(conn, cur.lastrowid)


def update_account(db: Database, account_id: int, data: dict) -> dict:
    with db.transaction() as conn:
        current = _get_account(conn, account_id)
        values = _validate(conn, data, current)
        if "currency" in values and values["currency"] != current["currency"] and current["movements"]:
            raise ConflictError("La valuta di un conto con operazioni non si può cambiare.")
        if "opened_on" in values and current["movements"]:
            first = _first_movement(conn, account_id)
            if first and values["opened_on"] > first:
                raise ValidationError(
                    f"Il conto ha operazioni dal {_it_date(first)}: la data di apertura non può essere successiva."
                )
        if "type_id" in values and values["type_id"] != current["type_id"]:
            _check_type_change(conn, current, values["type_id"])
        if not values:
            return current
        values["updated_at"] = now_iso()
        sets = ", ".join(f"{k} = ?" for k in values)
        try:
            conn.execute(f"UPDATE accounts SET {sets} WHERE id = ?", (*values.values(), account_id))
        except sqlite3.IntegrityError:
            raise ConflictError(f"Esiste già un conto chiamato '{values.get('name')}'.") from None
        return _get_account(conn, account_id)


def _check_type_change(conn: sqlite3.Connection, current: dict, new_type_id: int) -> None:
    """Changing behavior must not orphan behavior-specific data (savings rates, assets)."""
    new_behavior = conn.execute("SELECT behavior FROM account_types WHERE id = ?", (new_type_id,)).fetchone()[0]
    if new_behavior == current["behavior"]:
        return
    for table, behavior, what in _BEHAVIOR_DATA:
        if current["behavior"] == behavior and _table_exists(conn, table):
            if conn.execute(f"SELECT 1 FROM {table} WHERE account_id = ? LIMIT 1", (current["id"],)).fetchone():
                raise ConflictError(f"Il conto ha {what}: non può cambiare in un tipo con comportamento diverso.")


# (table with an account_id column, behavior that owns it, Italian description)
_BEHAVIOR_DATA: list[tuple[str, str, str]] = [
    ("savings_rates", "savings", "dei tassi di rendimento"),
    ("assets", "investment", "degli asset"),
]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def _first_movement(conn: sqlite3.Connection, account_id: int) -> str | None:
    return conn.execute(
        "SELECT MIN(date) FROM transactions WHERE from_account_id = ? OR to_account_id = ?",
        (account_id, account_id),
    ).fetchone()[0]


def _it_date(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}/{m}/{y}"


def delete_account(db: Database, account_id: int) -> None:
    with db.transaction() as conn:
        acc = _get_account(conn, account_id)
        if acc["movements"]:
            raise ConflictError("Il conto ha delle operazioni: archivialo invece di eliminarlo.")
        for table, _, what in _BEHAVIOR_DATA:
            if _table_exists(conn, table) and conn.execute(
                f"SELECT 1 FROM {table} WHERE account_id = ? LIMIT 1", (account_id,)
            ).fetchone():
                if table == "assets":
                    raise ConflictError("Il conto ha degli asset: eliminali o archivia il conto.")
                conn.execute(f"DELETE FROM {table} WHERE account_id = ?", (account_id,))
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
