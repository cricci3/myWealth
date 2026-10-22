"""JSON API endpoints. Thin glue: validation and logic live in the domain modules."""

from __future__ import annotations

import logging

from . import __version__, accounts, analytics, categories, fx, home, investments, money, savings, settings, transactions
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


def refresh_market(ctx, force: bool = False, wait: bool = False) -> dict:
    """Exchange rates and asset prices, in one background job."""
    def work() -> dict:
        provider = ctx.provider()
        rates = fx.refresh(ctx.db, provider, force=force)
        prices = investments.refresh_prices(ctx.db, provider, force=force)
        # merged view for the UI: errors keyed by currency or ticker
        return {"updated": rates["updated"] + prices["updated"], "errors": {**rates["errors"], **prices["errors"]},
                "skipped": rates["skipped"] + prices["skipped"]}

    return ctx.run_job("market", work, wait=wait)




@routes.get("fx")
def fx_status(ctx, req: Request):
    job = ctx.jobs.get("market", {})
    return {
        "rates": fx.status(ctx.db),
        "offline": settings.get(ctx.db, "offline_mode"),
        "running": job.get("running", False),
        "last": {k: job.get(k) for k in ("result", "error", "at")} if job else None,
    }


@routes.post("fx/refresh")
def fx_refresh(ctx, req: Request):
    refresh_market(ctx, force=True, wait=True)
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


# --------------------------------------------------------------------- savings


@routes.get("savings/<id>")
def savings_overview(ctx, req: Request):
    return savings.overview(ctx.db, req.params["id"])


@routes.post("savings/<id>/rates")
def savings_add_rate(ctx, req: Request):
    rate = savings.add_rate(ctx.db, req.params["id"], req.body())
    return {"rate": rate, "generated": savings.generate(ctx.db, account_id=req.params["id"])}


@routes.delete("savings/<id>/rates/<rate_id>")
def savings_delete_rate(ctx, req: Request):
    savings.delete_rate(ctx.db, req.params["id"], req.params["rate_id"])
    return {"ok": True}


@routes.post("savings/<id>/recalculate")
def savings_recalculate(ctx, req: Request):
    return {"generated": savings.recalculate(ctx.db, req.params["id"], req.body().get("from_month"))}


# ----------------------------------------------------------------- investments


@routes.get("investments")
def investment_accounts(ctx, req: Request):
    return investments.list_accounts(ctx.db)


@routes.get("investments/<id>")
def investment_portfolio(ctx, req: Request):
    return investments.portfolio(ctx.db, req.params["id"])


@routes.post("investments/refresh")
def investment_refresh(ctx, req: Request):
    refresh_market(ctx, force=True, wait=True)
    return fx_status(ctx, req)


@routes.get("market/search")
def market_search(ctx, req: Request):
    return investments.search(ctx.provider(), req.q("q", ""))


@routes.post("investments/<id>/assets")
def create_asset(ctx, req: Request):
    asset = investments.create_asset(ctx.db, ctx.provider(), req.params["id"], req.body())
    investments.refresh_prices(ctx.db, ctx.provider(), tickers=[asset["ticker"]])
    fx.refresh(ctx.db, ctx.provider())  # the instrument may bring a new currency
    return asset


@routes.put("assets/<id>")
def update_asset(ctx, req: Request):
    out = investments.update_asset(ctx.db, ctx.provider(), req.params["id"], req.body())
    if "ticker" in out:
        investments.refresh_prices(ctx.db, ctx.provider(), tickers=[out["ticker"]])
    return out


@routes.delete("assets/<id>")
def delete_asset(ctx, req: Request):
    investments.delete_asset(ctx.db, req.params["id"])
    return {"ok": True}


@routes.post("assets/<id>/trades")
def add_trade(ctx, req: Request):
    out = investments.add_trade(ctx.db, req.params["id"], req.body())
    investments.refresh_prices(ctx.db, ctx.provider())  # older history may be needed now
    return out


@routes.put("trades/<id>")
def update_trade(ctx, req: Request):
    out = investments.update_trade(ctx.db, req.params["id"], req.body())
    investments.refresh_prices(ctx.db, ctx.provider())
    return out


@routes.delete("trades/<id>")
def delete_trade(ctx, req: Request):
    investments.delete_trade(ctx.db, req.params["id"])
    return {"ok": True}


# ------------------------------------------------------------------------ home


@routes.get("home")
def home_summary(ctx, req: Request):
    return home.summary(ctx.db)


@routes.get("home/history")
def home_history(ctx, req: Request):
    return home.history(ctx.db, req.q("range") or settings.get(ctx.db, "home_range"))


# ------------------------------------------------------------------- analytics


@routes.get("analytics/categories")
def analytics_categories(ctx, req: Request):
    return analytics.expenses_by_category(ctx.db, req.q("from"), req.q("to"), req.q("account"))


@routes.get("analytics/monthly")
def analytics_monthly(ctx, req: Request):
    return analytics.monthly(ctx.db, year=req.q_int("year"), months=req.q_int("months", 12))


@routes.get("analytics/accounts")
def analytics_accounts(ctx, req: Request):
    return analytics.account_report(ctx.db, req.q("from"), req.q("to"))


@routes.get("analytics/networth")
def analytics_networth(ctx, req: Request):
    return analytics.net_worth(ctx.db)
