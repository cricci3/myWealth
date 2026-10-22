from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from mywealth import app, instance, paths
from mywealth.paths import LOCK_FILENAME


def test_data_dir_env_override(isolated_data_dir):
    assert paths.data_dir() == isolated_data_dir


def test_data_dir_default(monkeypatch, tmp_path):
    monkeypatch.delenv(paths.ENV_DATA_DIR)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setattr(paths.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(paths.sys, "platform", "win32")
    assert paths.data_dir() == tmp_path / "Roaming" / "myWealth"
    monkeypatch.setattr(paths.sys, "platform", "linux")
    assert paths.data_dir() == tmp_path / "home" / ".mywealth"


def _run_in_thread(argv, gui=False):
    result = {}
    thread = threading.Thread(target=lambda: result.setdefault("code", app.run(argv, gui=gui)))
    thread.start()
    return thread, result


def _wait_for_port(lock_path: Path, timeout=10) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            port = json.loads(lock_path.read_text()).get("port")
        except (OSError, ValueError):
            port = None
        if port and instance.ping(port):
            return port
        time.sleep(0.05)
    raise AssertionError("server did not start")


def _shutdown(port: int) -> None:
    # The token is only in the page: read it the way the browser does.
    import http.client
    import re

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", "/")
    html = conn.getresponse().read().decode()
    token = re.search(r'name="mywealth-token" content="([^"]+)"', html).group(1)
    conn.request("POST", "/api/shutdown", headers={"X-MyWealth-Token": token})
    assert conn.getresponse().status == 200
    conn.close()


def test_run_creates_db_and_stops_from_ui(isolated_data_dir):
    thread, result = _run_in_thread(["--no-browser", "--port", "0"])
    port = _wait_for_port(isolated_data_dir / LOCK_FILENAME)
    assert (isolated_data_dir / paths.DB_FILENAME).exists()

    # a second start doesn't launch another server
    assert app.run(["--no-browser", "--port", "0"]) == 0

    _shutdown(port)
    thread.join(timeout=10)
    assert result["code"] == 0
    assert not (isolated_data_dir / LOCK_FILENAME).exists()


def test_demo_uses_temporary_folder(isolated_data_dir, tmp_path, monkeypatch):
    demo_root = tmp_path / "demo"
    demo_root.mkdir()
    created = []

    def fake_mkdtemp(prefix):
        d = demo_root / f"{prefix}x"
        d.mkdir()
        created.append(d)
        return str(d)

    monkeypatch.setattr(app.tempfile, "mkdtemp", fake_mkdtemp)
    thread, result = _run_in_thread(["--demo", "--no-browser", "--port", "0"])
    while not created:
        time.sleep(0.01)
    port = _wait_for_port(created[0] / LOCK_FILENAME)
    _shutdown(port)
    thread.join(timeout=10)

    assert result["code"] == 0
    assert not isolated_data_dir.exists()  # the regular data folder was never touched
    assert not created[0].exists()  # and the demo folder is gone


def test_gui_mode_logs_to_file(isolated_data_dir):
    thread, result = _run_in_thread(["--no-browser", "--port", "0"], gui=True)
    port = _wait_for_port(isolated_data_dir / LOCK_FILENAME)
    _shutdown(port)
    thread.join(timeout=10)
    log = (isolated_data_dir / paths.LOGS_DIRNAME / "mywealth.log").read_text(encoding="utf-8")
    assert "running at" in log


def test_newer_database_is_refused(isolated_data_dir):
    from mywealth.db import LATEST_VERSION, Database

    db = Database(isolated_data_dir / paths.DB_FILENAME)
    db.migrate()
    with db.connect() as conn:
        conn.execute("INSERT INTO schema_version VALUES (?, 'x')", (LATEST_VERSION + 1,))
    assert app.run(["--no-browser", "--port", "0"]) == 1
    assert not (isolated_data_dir / LOCK_FILENAME).exists()


def test_version_flag(capsys):
    with pytest.raises(SystemExit):
        app.parse_args(["--version"])
    assert "myWealth" in capsys.readouterr().out
