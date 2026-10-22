from __future__ import annotations

import threading

import pytest

from mywealth import __version__
from mywealth.db import LATEST_VERSION
from mywealth.server import AppContext, make_server


def test_binds_only_loopback(server):
    httpd, _ = server
    assert httpd.server_address[0] == "127.0.0.1"


def test_index_injects_token(server):
    _, client = server
    status, headers, body = client.request("GET", "/", token=None)
    assert status == 200
    assert client.token.encode() in body
    assert b"__MYWEALTH_TOKEN__" not in body
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert headers["Cache-Control"] == "no-store"


def test_static_assets_served(server):
    _, client = server
    for path, ctype in [("/js/main.js", "javascript"), ("/app.css", "text/css"), ("/icon.svg", "svg")]:
        status, headers, _ = client.request("GET", path, token=None)
        assert status == 200
        assert ctype in headers["Content-Type"]


@pytest.mark.parametrize("path", ["/../pyproject.toml", "/..%2f..%2fdb.py", "/missing.js", "/web/../server.py"])
def test_static_rejects_traversal_and_missing(server, path):
    _, client = server
    status, _, _ = client.request("GET", path, token=None)
    assert status == 404


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8777", "127.0.0.1.evil.example", "192.168.1.10"])
def test_foreign_host_rejected(server, host):
    _, client = server
    assert client.request("GET", "/", token=None, host=host)[0] == 403
    assert client.request("GET", "/api/status", host=host)[0] == 403


def test_localhost_host_allowed(server):
    _, client = server
    assert client.request("GET", "/api/status", host=f"localhost:{client.port}")[0] == 200


@pytest.mark.parametrize("token", [None, "", "wrong"])
def test_api_requires_token(server, token):
    _, client = server
    status, data = client.json("GET", "/api/status", token=token)
    assert status == 403
    assert "error" in data


def test_ping_needs_no_token_and_leaks_nothing(server):
    _, client = server
    status, data = client.json("GET", "/ping", token=None)
    assert status == 200
    assert data == {"app": "mywealth"}


def test_status(server, isolated_data_dir):
    _, client = server
    status, data = client.json("GET", "/api/status")
    assert status == 200
    assert data == {
        "version": __version__,
        "demo": True,
        "data_dir": str(isolated_data_dir),
        "schema_version": LATEST_VERSION,
    }


def test_settings_roundtrip(server):
    _, client = server
    assert client.json("GET", "/api/settings") == (200, {"theme": "system"})
    assert client.json("PUT", "/api/settings", {"theme": "dark"}) == (200, {"theme": "dark"})
    assert client.json("GET", "/api/settings") == (200, {"theme": "dark"})


@pytest.mark.parametrize("body", [{"theme": "neon"}, {"nope": 1}, b"not json", b"[1, 2]"])
def test_settings_bad_input(server, body):
    _, client = server
    status, data = client.json("PUT", "/api/settings", body)
    assert status == 400
    assert "error" in data


def test_unknown_endpoint(server):
    _, client = server
    assert client.json("GET", "/api/nope")[0] == 404
    assert client.json("DELETE", "/")[0] == 405


def test_shutdown_stops_server(server):
    httpd, client = server
    thread = threading.Thread(target=httpd.serve_forever)
    # the fixture already runs serve_forever; stop it first and run our own loop to join on
    httpd.shutdown()
    thread.start()
    assert client.json("POST", "/api/shutdown") == (200, {"ok": True})
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_make_server_skips_busy_port(db, isolated_data_dir):
    ctx = AppContext(db=db, data_dir=isolated_data_dir)
    first = make_server(ctx, 0)
    try:
        second = make_server(ctx, first.port)
        try:
            assert second.port != first.port
        finally:
            second.server_close()
    finally:
        first.server_close()
