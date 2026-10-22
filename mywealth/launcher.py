"""Starting things outside the server: a demo instance, the data folder in Explorer."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from . import instance
from .errors import AppError

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
