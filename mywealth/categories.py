"""Categories of operations: expense, income and transfer natures."""

from __future__ import annotations

import sqlite3

from .db import Database
from .errors import ConflictError, NotFoundError, ValidationError

NATURES = ("expense", "income", "transfer")
NATURE_OF_KIND = {"expense": "expense", "income": "income", "transfer": "transfer", "interest": "income", "fee": "expense"}
MAX_NAME = 60


def _dict(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "nature": r["nature"],
        "system_key": r["system_key"],
        "archived": bool(r["archived"]),
        "used": r["used"],
    }


_SQL = """SELECT c.*, (SELECT COUNT(*) FROM transactions t WHERE t.category_id = c.id) AS used
          FROM categories c"""


def list_categories(db: Database) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(f"{_SQL} ORDER BY c.nature, c.name = 'Altro', c.name COLLATE NOCASE").fetchall()
    return [_dict(r) for r in rows]


def get_category(db: Database, cat_id: int) -> dict:
    with db.connect() as conn:
        row = conn.execute(f"{_SQL} WHERE c.id = ?", (cat_id,)).fetchone()
    if not row:
        raise NotFoundError("Categoria non trovata.")
    return _dict(row)


def system_category(conn: sqlite3.Connection, key: str) -> int:
    row = conn.execute("SELECT id FROM categories WHERE system_key = ?", (key,)).fetchone()
    if row:
        return row[0]
    # Recreated on demand if the user managed to lose it (e.g. an old import).
    nature = {"interest": "income", "dividends": "income", "fees": "expense", "transfer": "transfer"}[key]
    name = {"interest": "Interessi", "dividends": "Dividendi", "fees": "Commissioni bancarie", "transfer": "Trasferimento"}[key]
    existing = conn.execute("SELECT id FROM categories WHERE name = ? AND nature = ?", (name, nature)).fetchone()
    if existing:
        conn.execute("UPDATE categories SET system_key = ? WHERE id = ?", (key, existing[0]))
        return existing[0]
    return conn.execute(
        "INSERT INTO categories (name, nature, system_key) VALUES (?, ?, ?)", (name, nature, key)
    ).lastrowid


def check_category(conn: sqlite3.Connection, cat_id, nature: str, allow_archived_id: int | None = None) -> int:
    try:
        cat_id = int(cat_id)
    except (TypeError, ValueError):
        raise ValidationError("Scegli una categoria.") from None
    row = conn.execute("SELECT nature, archived FROM categories WHERE id = ?", (cat_id,)).fetchone()
    if not row:
        raise ValidationError("Categoria non trovata.")
    if row["nature"] != nature:
        raise ValidationError("La categoria non è adatta a questo tipo di operazione.")
    if row["archived"] and cat_id != allow_archived_id:
        raise ValidationError("La categoria è archiviata.")
    return cat_id


def _clean_name(value) -> str:
    name = " ".join(str(value or "").split())
    if not name:
        raise ValidationError("Il nome è obbligatorio.")
    if len(name) > MAX_NAME:
        raise ValidationError(f"Nome troppo lungo (max {MAX_NAME} caratteri).")
    return name


def create_category(db: Database, data: dict) -> dict:
    name = _clean_name(data.get("name"))
    nature = data.get("nature")
    if nature not in NATURES:
        raise ValidationError("Natura della categoria non valida.")
    with db.transaction() as conn:
        try:
            cat_id = conn.execute("INSERT INTO categories (name, nature) VALUES (?, ?)", (name, nature)).lastrowid
        except sqlite3.IntegrityError:
            raise ConflictError(f"Esiste già la categoria '{name}'.") from None
    return get_category(db, cat_id)


def update_category(db: Database, cat_id: int, data: dict) -> dict:
    current = get_category(db, cat_id)
    fields: dict = {}
    if "name" in data:
        fields["name"] = _clean_name(data["name"])
    if "archived" in data:
        if data["archived"] and current["system_key"]:
            raise ConflictError("Questa categoria è usata dall'app e non si può archiviare.")
        fields["archived"] = 1 if data["archived"] else 0
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        with db.transaction() as conn:
            try:
                conn.execute(f"UPDATE categories SET {sets} WHERE id = ?", (*fields.values(), cat_id))
            except sqlite3.IntegrityError:
                raise ConflictError(f"Esiste già la categoria '{fields['name']}'.") from None
    return get_category(db, cat_id)


def delete_category(db: Database, cat_id: int, move_to=None) -> None:
    """Delete a category; its operations move to `move_to` (required if it is used)."""
    cat = get_category(db, cat_id)
    if cat["system_key"]:
        raise ConflictError("Questa categoria è usata dall'app e non si può eliminare.")
    with db.transaction() as conn:
        if cat["used"]:
            if move_to in (None, ""):
                raise ValidationError("La categoria è usata: scegli dove spostare le operazioni.")
            target = check_category(conn, move_to, cat["nature"])
            if target == cat_id:
                raise ValidationError("Scegli una categoria diversa.")
            conn.execute("UPDATE transactions SET category_id = ? WHERE category_id = ?", (target, cat_id))
        conn.execute("DELETE FROM categories WHERE id = ?", (cat_id,))
