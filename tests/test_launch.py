"""Shortcuts, app window and idle shutdown. Nothing here touches the real Start menu,
desktop or browser: every external call is replaced."""

from __future__ import annotations

import subprocess
import threading
import time

import pytest

from mywealth import app, launcher, settings, shortcuts
from mywealth.server import AppContext


@pytest.fixture
def fake_windows(monkeypatch, tmp_path):
    locs = {k: tmp_path / k / "myWealth.lnk" for k in ("start_menu", "desktop", "startup")}
    monkeypatch.setattr(shortcuts, "is_supported", lambda: True)
    monkeypatch.setattr(shortcuts, "locations", lambda: locs)
    calls = []

    def fake_run(cmd, env=None, **kw):
        calls.append((cmd, env))
        from pathlib import Path

        Path(env["MW_LNK"]).write_text("lnk")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(shortcuts.subprocess, "run", fake_run)
    return locs, calls


def test_install_and_uninstall(fake_windows, monkeypatch, tmp_path):
    locs, calls = fake_windows
    exe = tmp_path / "mywealth-gui.exe"
    exe.write_text("")
    monkeypatch.setattr(shortcuts, "gui_executable", lambda: exe)
    made = shortcuts.install(desktop=True)
    assert made == [locs["start_menu"], locs["desktop"]]
    env = calls[0][1]
    assert env["MW_TARGET"] == str(exe) and env["MW_ARGS"] == ""
    assert env["MW_WD"] == str(shortcuts.PROJECT_DIR) and env["MW_ICON"].endswith("icon.ico,0")
    assert shortcuts.status()["start_menu"] and not shortcuts.status()["startup"]
    assert shortcuts.uninstall() == ["start_menu", "desktop"]


def test_vbs_fallback_when_gui_exe_missing(fake_windows, monkeypatch, tmp_path):
    locs, calls = fake_windows
    monkeypatch.setattr(shortcuts, "gui_executable", lambda: tmp_path / "missing.exe")
    monkeypatch.setattr(shortcuts.shutil, "which", lambda name: r"C:\uv\uv.exe")
    shortcuts.create("start_menu", data_dir=tmp_path / "data")
    env = calls[0][1]
    assert env["MW_TARGET"].endswith("wscript.exe")
    script = (tmp_path / "data" / shortcuts.VBS_NAME).read_text(encoding="utf-8")
    assert "run --project" in script and "mywealth-gui" in script and ", 0, False" in script


def test_powershell_failure_is_reported(fake_windows, monkeypatch, tmp_path):
    monkeypatch.setattr(shortcuts, "gui_executable", lambda: tmp_path)
    monkeypatch.setattr(shortcuts.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "blocked by policy"))
    with pytest.raises(shortcuts.ShortcutError, match="blocked"):
        shortcuts.create("desktop")


def test_cli_shortcuts(fake_windows, monkeypatch, tmp_path, capsys):
    exe = tmp_path / "gui.exe"
    exe.write_text("")
    monkeypatch.setattr(shortcuts, "gui_executable", lambda: exe)
    assert app.run(["--install-shortcuts", "--no-desktop"]) == 0
    assert "Creato" in capsys.readouterr().out
    assert app.run(["--uninstall-shortcuts"]) == 0
    assert "start_menu" in capsys.readouterr().out
    monkeypatch.setattr(shortcuts, "is_supported", lambda: False)
    assert app.run(["--install-shortcuts"]) == 1


def test_open_window(monkeypatch, tmp_path):
    started, opened = [], []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda cmd, **kw: started.append(cmd))
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    monkeypatch.setattr(launcher, "edge_path", lambda: r"C:\Edge\msedge.exe")
    launcher.open_window("http://127.0.0.1:1/", tmp_path, "app")
    assert started[0][0].endswith("msedge.exe") and "--app=http://127.0.0.1:1/" in started[0]
    assert f"--user-data-dir={tmp_path / 'browser-profile'}" in started[0]
    launcher.open_window("http://127.0.0.1:1/", tmp_path, "browser")
    monkeypatch.setattr(launcher, "edge_path", lambda: None)
    launcher.open_window("http://127.0.0.1:1/", tmp_path, "app")
    assert opened == ["http://127.0.0.1:1/"] * 2


def test_idle_watch_stops_server(db, isolated_data_dir):
    ctx = AppContext(db=db, data_dir=isolated_data_dir)
    settings.update(db, {"idle_minutes": 1})
    stopped = threading.Event()

    class FakeServer:
        def request_shutdown(self):
            stopped.set()

    ctx.last_heartbeat = time.monotonic()
    t = app.watch_idle(ctx, FakeServer(), check_every=0.05)
    time.sleep(0.2)
    assert not stopped.is_set()  # heartbeat is recent
    ctx.last_heartbeat = time.monotonic() - 61
    assert stopped.wait(2)
    t.join(2)


def test_idle_watch_disabled_and_stops_with_server(db, isolated_data_dir):
    ctx = AppContext(db=db, data_dir=isolated_data_dir)
    settings.update(db, {"idle_minutes": 0})
    ctx.last_heartbeat = time.monotonic() - 10_000
    t = app.watch_idle(ctx, None, check_every=0.05)
    time.sleep(0.2)
    assert t.is_alive()
    ctx.stopping.set()
    t.join(2)
    assert not t.is_alive()


def test_heartbeat_and_system_api(server):
    httpd, client = server
    before = httpd.ctx.last_heartbeat
    time.sleep(0.01)
    assert client.json("POST", "/api/heartbeat") == (200, {"ok": True})
    assert httpd.ctx.last_heartbeat > before
    status, info = client.json("GET", "/api/system")
    assert status == 200 and "supported" in info["shortcuts"]
    assert client.json("POST", "/api/shortcuts", {"kind": "evil"})[0] == 400


@pytest.mark.parametrize("bad", [{"launch_mode": "kiosk"}, {"idle_minutes": -1}, {"port": 80}, {"port": "x"}])
def test_launch_settings_validation(db, bad):
    with pytest.raises(settings.SettingsError):
        settings.update(db, bad)


def test_port_setting_used_when_no_flag(isolated_data_dir, monkeypatch):
    captured = {}
    real = app.make_server

    def spy(ctx, port, *a, **k):
        captured["port"] = port
        return real(ctx, 0)

    monkeypatch.setattr(app, "make_server", spy)
    from mywealth.db import Database
    from mywealth.paths import DB_FILENAME

    db = Database(isolated_data_dir / DB_FILENAME)
    db.migrate()
    settings.update(db, {"port": 9123, "fx_auto_refresh": False})
    thread = threading.Thread(target=app.run, args=(["--no-browser"],))
    thread.start()
    from .test_app import _shutdown, _wait_for_port
    from mywealth.paths import LOCK_FILENAME

    port = _wait_for_port(isolated_data_dir / LOCK_FILENAME)
    _shutdown(port)
    thread.join(10)
    assert captured["port"] == 9123
