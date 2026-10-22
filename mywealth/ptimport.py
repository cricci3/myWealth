"""Import a PortfolioTracker `portfolio.json` into an investment account.

Every contribution becomes a buy on that account. Buys need liquidity, so the money can
come either from the liquidity already on the account, or from another account through
one transfer per contribution (dated like the contribution). Everything is imported in a
single transaction: if one buy fails (e.g. not enough liquidity), nothing is saved.
"""

from __future__ import annotations

import json
from decimal import Decimal

from . import accounts, investments, market, money, transactions
from .db import Database, now_iso
from .errors import ValidationError

MAX_ASSETS = 500


def parse(raw: bytes) -> dict:
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise ValidationError("Il file non è un portfolio.json valido.") from None
    if not isinstance(data, dict) or not isinstance(data.get("assets"), list):
        raise ValidationError("Il file non è un portfolio.json di PortfolioTracker.")
    if len(data["assets"]) > MAX_ASSETS:
        raise ValidationError("Troppi asset nel file.")
    base = str(data.get("base_currency") or "EUR").upper()
    assets = []
    for a in data["assets"]:
        if not isinstance(a, dict) or not a.get("ticker"):
            raise ValidationError("Asset senza ticker nel file.")
        contribs = []
        for c in a.get("contributions") or []:
            if not isinstance(c, dict):
                raise ValidationError("Contributo non valido nel file.")
            contribs.append({
                "date": money.parse_date(c.get("date")).isoformat(),
                "amount": Decimal(str(c.get("amount"))),
                "price": None if c.get("price") in (None, "") else Decimal(str(c.get("price"))),
                "note": str(c.get("note") or "")[:200],
            })
        assets.append({"ticker": str(a["ticker"]).upper(), "name": str(a.get("name") or ""),
                       "exchange": str(a.get("exchange") or ""), "currency": str(a.get("currency") or base),
                       "input_symbol": str(a.get("input_symbol") or a["ticker"]), "contributions": contribs})
    return {"base_currency": base, "assets": assets}


def summary(raw: bytes) -> dict:
    pf = parse(raw)
    total = sum((c["amount"] for a in pf["assets"] for c in a["contributions"]), Decimal(0))
    dates = sorted(c["date"] for a in pf["assets"] for c in a["contributions"])
    return {
        "base_currency": pf["base_currency"],
        "assets": [{"ticker": a["ticker"], "name": a["name"], "contributions": len(a["contributions"]),
                    "amount": money.fmt_decimal(sum((c["amount"] for c in a["contributions"]), Decimal(0)))}
                   for a in pf["assets"]],
        "total": money.fmt_decimal(total),
        "first_date": dates[0] if dates else None,
        "contributions": len(dates),
    }


def import_portfolio(db: Database, raw: bytes, account_id: int, source_account_id=None) -> dict:
    pf = parse(raw)
    with db.transaction() as conn:
        acc = investments._investment_account(conn, account_id)
        if acc["archived"]:
            raise ValidationError("Il conto è archiviato.")
        if acc["currency"] != pf["base_currency"]:
            raise ValidationError(
                f"Il portafoglio è in {pf['base_currency']} ma il conto è in {acc['currency']}: scegli un conto in "
                f"{pf['base_currency']}."
            )
        existing = {r[0] for r in conn.execute("SELECT ticker FROM assets WHERE account_id = ?", (account_id,))}
        clash = [a["ticker"] for a in pf["assets"] if a["ticker"] in existing]
        if clash:
            raise ValidationError(f"Già presenti nel conto: {', '.join(clash)}. Eliminali prima di importare.")
        src = None
        if source_account_id not in (None, ""):
            src = accounts.account_row(conn, source_account_id)
            if src["archived"]:
                raise ValidationError(f"Il conto '{src['name']}' è archiviato.")
            if src["id"] == acc["id"]:
                raise ValidationError("Il conto di provenienza deve essere diverso.")
        # buys in date order, so the liquidity check sees the transfers that fund them
        flat = sorted(((a, c) for a in pf["assets"] for c in a["contributions"]), key=lambda ac: ac[1]["date"])
        ids: dict[str, int] = {}
        for a in pf["assets"]:
            ids[a["ticker"]] = conn.execute(
                "INSERT INTO assets (account_id, ticker, name, exchange, currency, input_symbol, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (acc["id"], market.check_symbol(a["ticker"]), a["name"][:120] or a["ticker"], a["exchange"],
                 a["currency"], a["input_symbol"][:40], now_iso()),
            ).lastrowid
        transfers = 0
        for a, c in flat:
            amount = money.fmt(money.to_minor(c["amount"], acc["currency"]), acc["currency"])
            if src is not None:
                if src["currency"] != acc["currency"]:
                    raise ValidationError("Il conto di provenienza deve avere la stessa valuta del conto investimenti.")
                transactions.create_in(conn, {
                    "kind": "transfer", "date": c["date"], "from_account_id": src["id"], "to_account_id": acc["id"],
                    "amount": amount, "description": f"Versamento per {a['ticker']} (da PortfolioTracker)",
                })
                transfers += 1
            asset = conn.execute("SELECT * FROM assets WHERE id = ?", (ids[a["ticker"]],)).fetchone()
            try:
                investments._write_trade(conn, asset, acc, {
                    "kind": "buy", "date": c["date"], "amount": amount, "note": c["note"],
                    "price": None if c["price"] is None else format(c["price"], "f"),
                }, None)
            except ValidationError as e:
                raise ValidationError(f"{a['ticker']} del {c['date']}: {e}") from None
    return {"assets": len(pf["assets"]), "buys": len(flat), "transfers": transfers}
