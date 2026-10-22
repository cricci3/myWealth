"""Single instance: a lock file in the data folder records the PID and port of the running server.

A second start finds the lock, checks that a myWealth server really answers on that port
and, if so, just reopens the window on it. A lock left behind by a crash (nobody answers)
is taken over.
"""

from __future__ import annotations

import http.client
import json
import os
import time
from pathlib import Path

from .paths import LOCK_FILENAME

PING_PATH = "/ping"
APP_ID = "mywealth"
# A lock without a port belongs to an instance that is still starting up.
STARTUP_GRACE_SECONDS = 10


class InstanceLock:
    def __init__(self, path: Path):
        self.path = path
        self.owned = False

    def set_port(self, port: int) -> None:
        self._write({"pid": os.getpid(), "port": port})

    def release(self) -> None:
        if not self.owned:
            return
        self.owned = False
        for _ in range(40):
            try:
                if _read(self.path).get("pid") == os.getpid():
                    self.path.unlink()
                return
            except FileNotFoundError:
                return
            except PermissionError:
                time.sleep(0.05)  # Windows: another process is reading the lock right now

    def _write(self, data: dict) -> None:
        # Written in place: on Windows a file that another process is reading can't be
        # replaced, while readers treat a half-written lock as "still starting up".
        self.path.write_text(json.dumps(data), encoding="utf-8")


def acquire(data_dir: Path, wait: float = STARTUP_GRACE_SECONDS) -> InstanceLock | int:
    """Take the lock, or return the port of the instance already running."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / LOCK_FILENAME
    deadline = time.monotonic() + wait
    while True:
        if time.monotonic() > deadline + 10:
            raise TimeoutError(f"Could not take the instance lock {path}")
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            pass
        except PermissionError:
            time.sleep(0.05)  # Windows: the old lock is being deleted or read
            continue
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "port": None}, f)
            lock = InstanceLock(path)
            lock.owned = True
            return lock

        try:
            info = _read(path)
        except FileNotFoundError:
            continue  # released meanwhile: try again
        port = info.get("port")
        if isinstance(port, int) and ping(port):
            return port
        if port is None and _age(path) < STARTUP_GRACE_SECONDS and time.monotonic() < deadline:
            time.sleep(0.2)  # the other instance is still binding its port
            continue
        try:
            path.unlink()  # stale lock: nobody answers
        except FileNotFoundError:
            pass
        except PermissionError:
            time.sleep(0.05)


def ping(port: int, timeout: float = 1.0) -> bool:
    """True if a myWealth server answers on 127.0.0.1:<port>."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", PING_PATH, headers={"Host": f"127.0.0.1:{port}"})
        res = conn.getresponse()
        return res.status == 200 and json.loads(res.read() or b"{}").get("app") == APP_ID
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        conn.close()


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except FileNotFoundError:
        raise
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _age(path: Path) -> float:
    try:
        return time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return 0.0
