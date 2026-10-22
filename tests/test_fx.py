from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from mywealth import fx, market, transactions as tx
from mywealth.errors import ValidationError

from .helpers import cat, make_account


class FakeProvider(market.Provider):
    name = "yahoo"

    def __init__(self, rates: dict[str, dict[date, str]] | None = None, fail: bool = False):
        self.rates = rates or {}
        self.fail = fail
        self.calls: list[tuple[str, date]] = []

    def history(self, symbol, start):
        self.calls.append((symbol, start))
        if self.fail:
            raise market.MarketError("offline")
        series = self.rates.get(symbol[:3], {})
        return [(d, Decimal(r)) for d, r in sorted(series.items()) if d >= start]


TODAY = date.today()
D1, D2, D3 = TODAY - timedelta(days=30), TODAY - timedelta(days=20), TODAY - timedelta(days=10)


@pytest.fixture
def chf(db):
    return make_account(db, "Svizzero", "CHF", "100", opened=(TODAY - timedelta(days=40)).isoformat())


def expense(db, acc, day, amount="10"):
    return tx.create(db, {"kind": "expense", "account_id": acc["id"], "amount": amount, "date": day.isoformat(),
                          "category_id": cat(db, "Svago")})


def test_snapshot_rules(db, chf):
    with db.transaction() as conn:
        fx.store_rates(conn, "CHF", [(D1, Decimal("1.05")), (D3, Decimal("1.07"))], "yahoo")
    with db.connect() as conn:
        assert fx.snapshot(conn, "EUR", "2020-01-01") == ("1", "2020-01-01")
        assert fx.snapshot(conn, "CHF", D1.isoformat()) == ("1.05", D1.isoformat())
        assert fx.snapshot(conn, "CHF", D2.isoformat()) == ("1.05", D1.isoformat())  # most recent before
        assert fx.snapshot(conn, "CHF", "2000-01-01") == ("1.05", D1.isoformat())  # nothing before: nearest after
        assert fx.snapshot(conn, "USD", D2.isoformat()) == (None, None)
        series = fx.daily_series(conn, "CHF", D1 - timedelta(days=1), D3)
        assert series[D1 - timedelta(days=1)] == Decimal("1.05")
        assert series[D2] == Decimal("1.05") and series[D3] == Decimal("1.07")
        assert fx.latest_rate(conn, "CHF") == Decimal("1.07")


def test_refresh_fills_missing_operation_rates(db, chf):
    t = expense(db, chf, D2, "20")
    assert t["eur"] is None
    provider = FakeProvider({"CHF": {D1: "1.05", D2: "1.06", D3: "1.07"}})
    result = fx.refresh(db, provider)
    assert result["updated"] == ["CHF"] and not result["errors"]
    t = tx.get(db, t["id"])
    assert (t["from_rate"], t["from_rate_date"], t["eur"]) == ("1.06", D2.isoformat(), "21.20")
    # the download started a margin before the account opening
    assert provider.calls == [("CHFEUR=X", TODAY - timedelta(days=40 + fx.HISTORY_MARGIN_DAYS))]


def test_new_operations_get_the_rate_of_their_day(db, chf):
    fx.refresh(db, FakeProvider({"CHF": {D1: "1.05", D2: "1.06"}}))
    assert expense(db, chf, D2)["from_rate"] == "1.06"
    assert expense(db, chf, D3)["from_rate"] == "1.06"  # no newer rate yet


def test_snapshot_of_own_day_is_never_rewritten(db, chf):
    fx.refresh(db, FakeProvider({"CHF": {D2: "1.06"}}))
    t = expense(db, chf, D2)
    with db.transaction() as conn:
        fx.store_rates(conn, "CHF", [(D2, Decimal("1.50"))], "yahoo")
        fx.resnapshot(conn)
    assert tx.get(db, t["id"])["from_rate"] == "1.06"


def test_one_download_per_day(db, chf):
    provider = FakeProvider({"CHF": {D1: "1.05"}})
    fx.refresh(db, provider)
    assert fx.refresh(db, provider)["skipped"] == ["CHF"]
    assert len(provider.calls) == 1
    # next day: incremental download from the last fetch (minus a margin)
    fx.refresh(db, provider, today=TODAY + timedelta(days=1))
    assert provider.calls[-1] == ("CHFEUR=X", TODAY - timedelta(days=fx.HISTORY_MARGIN_DAYS))
    # forced refresh downloads again
    fx.refresh(db, provider, force=True, today=TODAY + timedelta(days=1))
    assert len(provider.calls) == 3


def test_older_history_needed_triggers_download(db, chf):
    from mywealth import accounts

    provider = FakeProvider({"CHF": {D1: "1.05"}})
    fx.refresh(db, provider)
    accounts.update_account(db, chf["id"], {"opened_on": (TODAY - timedelta(days=400)).isoformat()})
    fx.refresh(db, provider)
    assert len(provider.calls) == 2
    assert provider.calls[-1][1] == TODAY - timedelta(days=400 + fx.HISTORY_MARGIN_DAYS)


def test_offline_keeps_last_rate_and_reports_error(db, chf):
    fx.refresh(db, FakeProvider({"CHF": {D1: "1.05"}}))
    result = fx.refresh(db, FakeProvider(fail=True), force=True)
    assert result["errors"] == {"CHF": "offline"}
    st = fx.status(db)["CHF"]
    assert (st["rate"], st["date"], st["error"]) == ("1.05", D1.isoformat(), "offline")
    assert st["stale"] is True
    assert fx.refresh(db, market.OfflineProvider(), force=True)["errors"]["CHF"].startswith("Modalità offline")


def test_manual_rate(db, chf):
    t = expense(db, chf, D2, "10")
    rate = fx.add_manual(db, {"currency": "CHF", "date": D1.isoformat(), "rate": "1,04"})
    assert rate == {"currency": "CHF", "date": D1.isoformat(), "rate": "1.04", "source": "manual"}
    assert tx.get(db, t["id"])["eur"] == "10.40"
    # Yahoo never overwrites a manual rate of the same day
    fx.refresh(db, FakeProvider({"CHF": {D1: "1.10", D2: "1.06"}}))
    assert fx.rates_list(db, "CHF")[-1]["rate"] == "1.04"
    assert tx.get(db, t["id"])["from_rate"] == "1.06"  # a rate of its own day is now known
    # entered the other way round: 1 EUR = 0.5 CHF -> 2 EUR per CHF
    assert fx.add_manual(db, {"currency": "CHF", "date": D3.isoformat(), "rate": "0.5", "direction": "per_eur"})["rate"] == "2"
    fx.delete_manual(db, "CHF", D3.isoformat())
    with pytest.raises(ValidationError):
        fx.delete_manual(db, "CHF", D3.isoformat())


@pytest.mark.parametrize("data", [
    {"currency": "EUR", "rate": "1"},
    {"currency": "CHF", "rate": "0"},
    {"currency": "CHF", "rate": "abc"},
    {"currency": "CHF", "rate": "1", "date": (TODAY + timedelta(days=1)).isoformat()},
])
def test_manual_rate_validation(db, data):
    with pytest.raises(ValidationError):
        fx.add_manual(db, data)


def test_demo_provider_is_deterministic_and_offline():
    p = market.DemoProvider()
    a = p.history("CHFEUR=X", TODAY - timedelta(days=30))
    b = p.history("CHFEUR=X", TODAY - timedelta(days=10))
    assert a and b and dict(a)[b[0][0]] == b[0][1]
    assert all(Decimal("0.8") < r < Decimal("1.4") for _, r in a)
    assert p.network is False


def test_fx_api(server, db):
    httpd, client = server
    make_account(db, "Svizzero", "CHF", "1", opened=D1.isoformat())
    status, data = client.json("POST", "/api/fx/refresh")  # demo context: synthetic rates
    assert status == 200 and data["rates"]["CHF"]["rate"] and data["last"]["error"] is None
    assert client.json("POST", "/api/fx/rates", {"currency": "CHF", "rate": "1,1"})[0] == 200
    assert client.json("GET", "/api/fx/rates?currency=CHF")[0] == 200
    assert client.json("DELETE", f"/api/fx/rates/CHF/{TODAY.isoformat()}")[0] == 200
    client.json("PUT", "/api/settings", {"offline_mode": True})
    status, data = client.json("POST", "/api/fx/refresh")
    assert data["offline"] is True and "CHF" in data["last"]["result"]["errors"]
