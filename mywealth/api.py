"""JSON API endpoints. Thin glue: validation and logic live in the domain modules."""

from __future__ import annotations

import logging

from . import __version__, accounts, categories, fx, money, settings, transactions
from .router import Request, Router

log = logging.getLogger(__name__)

routes = Router()


# ------------------------------------------------------------------------- app


@routes.get("status")
def status(ctx, req: Request):
    return {
        "version": __version__,
        "demo": ctx.demo,
        "data_dir": str(ctx.data_dir),
        "schema_version": ctx.db.schema_version(),
    }


@routes.get("settings")
def get_settings(ctx, req: Request):
    return settings.load(ctx.db)


@routes.put("settings")
def put_settings(ctx, req: Request):
    return settings.update(ctx.db, req.body())


@routes.post("shutdown")
def shutdown(ctx, req: Request):
    log.info("Shutdown requested from the UI")
    ctx.request_shutdown()
    return {"ok": True}


@routes.get("currencies")
def currencies(ctx, req: Request):
    return money.currency_list()


# -------------------------------------------------------------------- accounts


@routes.get("account-types")
def list_account_types(ctx, req: Request):
    return accounts.list_types(ctx.db)


@routes.post("account-types")
def create_account_type(ctx, req: Request):
    return accounts.create_type(ctx.db, req.body())


@routes.put("account-types/<id>")
def update_account_type(ctx, req: Request):
    return accounts.update_type(ctx.db, req.params["id"], req.body())


@routes.delete("account-types/<id>")
def delete_account_type(ctx, req: Request):
    accounts.delete_type(ctx.db, req.params["id"])
    return {"ok": True}


@routes.get("accounts")
def list_accounts(ctx, req: Request):
    return accounts.list_accounts(ctx.db)


@routes.post("accounts")
def create_account(ctx, req: Request):
    return accounts.create_account(ctx.db, req.body())


@routes.get("accounts/<id>")
def get_account(ctx, req: Request):
    return accounts.get_account(ctx.db, req.params["id"])


@routes.put("accounts/<id>")
def update_account(ctx, req: Request):
    return accounts.update_account(ctx.db, req.params["id"], req.body())


@routes.delete("accounts/<id>")
def delete_account(ctx, req: Request):
    accounts.delete_account(ctx.db, req.params["id"])
    return {"ok": True}


# ------------------------------------------------------------------ categories


@routes.get("categories")
def list_categories(ctx, req: Request):
    return categories.list_categories(ctx.db)


@routes.post("categories")
def create_category(ctx, req: Request):
    return categories.create_category(ctx.db, req.body())


@routes.put("categories/<id>")
def update_category(ctx, req: Request):
    return categories.update_category(ctx.db, req.params["id"], req.body())


@routes.delete("categories/<id>")
def delete_category(ctx, req: Request):
    categories.delete_category(ctx.db, req.params["id"], req.q("move_to"))
    return {"ok": True}


# ---------------------------------------------------------------- transactions


@routes.get("transactions")
def list_transactions(ctx, req: Request):
    return transactions.list_transactions(
        ctx.db, req.query, limit=req.q_int("limit", transactions.DEFAULT_PAGE), offset=req.q_int("offset", 0)
    )


@routes.post("transactions")
def create_transaction(ctx, req: Request):
    return transactions.create(ctx.db, req.body())


@routes.get("transactions/<id>")
def get_transaction(ctx, req: Request):
    return transactions.get(ctx.db, req.params["id"])


@routes.put("transactions/<id>")
def update_transaction(ctx, req: Request):
    return transactions.update(ctx.db, req.params["id"], req.body())


@routes.delete("transactions/<id>")
def delete_transaction(ctx, req: Request):
    transactions.delete(ctx.db, req.params["id"])
    return {"ok": True}


# -------------------------------------------------------------------------- fx


def refresh_fx(ctx, force: bool = False, wait: bool = False) -> dict:
    return ctx.run_job("fx", lambda: fx.refresh(ctx.db, ctx.provider(), force=force), wait=wait)


@routes.get("fx")
def fx_status(ctx, req: Request):
    job = ctx.jobs.get("fx", {})
    return {
        "rates": fx.status(ctx.db),
        "offline": settings.get(ctx.db, "offline_mode"),
        "running": job.get("running", False),
        "last": {k: job.get(k) for k in ("result", "error", "at")} if job else None,
    }


@routes.post("fx/refresh")
def fx_refresh(ctx, req: Request):
    refresh_fx(ctx, force=True, wait=True)
    return fx_status(ctx, req)


@routes.get("fx/rates")
def fx_rates(ctx, req: Request):
    cur = req.q("currency")
    return fx.rates_list(ctx.db, money.check_currency(cur) if cur else None, limit=req.q_int("limit", 60))


@routes.post("fx/rates")
def fx_add_manual(ctx, req: Request):
    return fx.add_manual(ctx.db, req.body())


@routes.delete("fx/rates/<currency:str>/<day:str>")
def fx_delete_manual(ctx, req: Request):
    fx.delete_manual(ctx.db, money.check_currency(req.params["currency"]), str(req.params["day"]))
    return {"ok": True}
