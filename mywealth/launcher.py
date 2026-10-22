"""Starting things outside the server: a demo instance, the data folder in Explorer."""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from . import instance
from .errors import AppError

log = logging.getLogger(__name__)

NO_WINDOW = 0x08000000 if sys.platform.startswith("win") else 0  # CREATE_NO_WINDOW


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def launch_demo(timeout: float = 30) -> str:
    """Start `mywealth --demo` in a separate process (its own temporary data) and return its URL."""
    port = _free_port()
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, "-m", "mywealth", "--demo", "--no-browser", "--port", str(port)], **kwargs)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if instance.ping(port, timeout=0.5):
            return f"http://127.0.0.1:{port}/"
        time.sleep(0.3)
    raise AppError("La demo non si è avviata in tempo.")


def open_folder(path: Path) -> None:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # noqa: S606 - local folder chosen by the app, not by the user
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def edge_path() -> str | None:
    """Microsoft Edge, always present on Windows 10/11."""
    if not sys.platform.startswith("win"):
        return None
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            p = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if p.exists():
                return str(p)
    return shutil.which("msedge")


def open_window(url: str, data_dir: Path, mode: str = "app") -> None:
    """Open the UI: a dedicated Edge window without address bar and tabs (separate profile
    in <data dir>/browser-profile), or a tab of the default browser."""
    import webbrowser

    edge = edge_path() if mode == "app" else None
    if edge:
        profile = Path(data_dir) / "browser-profile"
        try:
            subprocess.Popen(
                [edge, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
                 "--window-size=1280,860"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return
        except OSError:
            log.warning("Could not start Edge, using the default browser")
    webbrowser.open(url)
