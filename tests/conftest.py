from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path

import pytest

from mywealth.db import Database
from mywealth.paths import ENV_DATA_DIR
from mywealth.server import AppContext, make_server


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch) -> Path:
    """Every test runs against a temporary data folder, never the real one."""
    path = tmp_path / "data"
    monkeypatch.setenv(ENV_DATA_DIR, str(path))
    return path


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests never reach Yahoo: the real provider fails as if offline."""
    from mywealth import market

    def blocked(*args, **kwargs):
        raise market.MarketError("network disabled in tests")

    for name in ("history", "search", "meta"):
        monkeypatch.setattr(market.YahooProvider, name, blocked)


@pytest.fixture
def db(isolated_data_dir) -> Database:
    database = Database(isolated_data_dir / "test.db")
    database.migrate()
    return database


class Client:
    def __init__(self, port: int, token: str):
        self.port = port
        self.token = token

    def request(self, method: str, path: str, body=None, token: str | None = "default", host: str | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        if token == "default":
            token = self.token
        if token is not None:
            headers["X-MyWealth-Token"] = token
        payload = None
        if body is not None:
            payload = body if isinstance(body, bytes) else json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        try:
            conn.request(method, path, body=payload, headers=headers)
            res = conn.getresponse()
            raw = res.read()
            return res.status, dict(res.getheaders()), raw
        finally:
            conn.close()

    def json(self, method: str, path: str, body=None, **kw):
        status, _, raw = self.request(method, path, body, **kw)
        return status, json.loads(raw)


@pytest.fixture
def server(db, isolated_data_dir):
    ctx = AppContext(db=db, data_dir=isolated_data_dir, demo=True)
    httpd = make_server(ctx, 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd, Client(httpd.port, ctx.token)
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)
