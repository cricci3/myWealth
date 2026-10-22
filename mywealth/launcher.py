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


def _find(rel: tuple[str, ...], exe: str, bases: tuple[str, ...]) -> str | None:
    if not sys.platform.startswith("win"):
        return None
    for var in bases:
        base = os.environ.get(var)
        if base:
            p = Path(base).joinpath(*rel, exe)
            if p.exists():
                return str(p)
    return shutil.which(exe)


def brave_path() -> str | None:
    """Brave, the user's browser on the PC (system-wide or per-user install)."""
    return _find(("BraveSoftware", "Brave-Browser", "Application"), "brave.exe",
                 ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"))


def edge_path() -> str | None:
    """Microsoft Edge, always present on Windows 10/11."""
    return _find(("Microsoft", "Edge", "Application"), "msedge.exe", ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"))


# Browser tried for each choice of the "app_browser" setting, in order; then the default browser tab.
_ORDER = {"auto": ("brave", "edge"), "brave": ("brave", "edge"), "edge": ("edge",), "default": ()}
# Separate profiles: no extensions, history or sync of the user's own browser profile.
_PROFILES = {"brave": "browser-profile-brave", "edge": "browser-profile"}


def available_browsers() -> dict[str, bool]:
    return {"brave": brave_path() is not None, "edge": edge_path() is not None}


def pick_browser(choice: str) -> tuple[str, str | None]:
    """(name, executable) of the app-window browser for a setting value; ("default", None) = browser tab."""
    finders = {"brave": brave_path, "edge": edge_path}
    for name in _ORDER.get(choice, _ORDER["auto"]):
        path = finders[name]()
        if path:
            return name, path
    return "default", None


def open_window(url: str, data_dir: Path, choice: str = "auto") -> str:
    """Open the UI in a dedicated window without address bar and tabs (Brave or Edge, with a
    profile of its own in the data folder), or in a tab of the default browser.
    Returns the browser used: "brave", "edge" or "default"."""
    import webbrowser

    name, exe = pick_browser(choice)
    if exe:
        profile = Path(data_dir) / _PROFILES[name]
        try:
            subprocess.Popen(
                [exe, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
                 "--window-size=1280,860"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return name
        except OSError:
            log.warning("Could not start %s, using the default browser", name)
    webbrowser.open(url)
    return "default"
