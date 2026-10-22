from __future__ import annotations

import json
import os
import socket
import time

from mywealth import instance
from mywealth.paths import LOCK_FILENAME


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_acquire_creates_and_releases_lock(tmp_path):
    lock = instance.acquire(tmp_path)
    assert isinstance(lock, instance.InstanceLock)
    path = tmp_path / LOCK_FILENAME
    assert json.loads(path.read_text()) == {"pid": os.getpid(), "port": None}
    lock.set_port(1234)
    assert json.loads(path.read_text()) == {"pid": os.getpid(), "port": 1234}
    lock.release()
    assert not path.exists()


def test_running_instance_is_detected(server, isolated_data_dir):
    httpd, _ = server
    (isolated_data_dir / LOCK_FILENAME).write_text(json.dumps({"pid": 1, "port": httpd.port}))
    assert instance.acquire(isolated_data_dir) == httpd.port


def test_stale_lock_is_taken_over(tmp_path):
    path = tmp_path / LOCK_FILENAME
    path.write_text(json.dumps({"pid": 999999, "port": _free_port()}))
    lock = instance.acquire(tmp_path)
    assert isinstance(lock, instance.InstanceLock)
    assert json.loads(path.read_text())["pid"] == os.getpid()


def test_corrupt_lock_is_taken_over(tmp_path):
    (tmp_path / LOCK_FILENAME).write_text("garbage")
    old = time.time() - instance.STARTUP_GRACE_SECONDS - 5
    os.utime(tmp_path / LOCK_FILENAME, (old, old))
    assert isinstance(instance.acquire(tmp_path), instance.InstanceLock)


def test_starting_instance_is_waited_for_then_taken_over(tmp_path):
    (tmp_path / LOCK_FILENAME).write_text(json.dumps({"pid": 1, "port": None}))
    start = time.monotonic()
    lock = instance.acquire(tmp_path, wait=0.5)
    assert isinstance(lock, instance.InstanceLock)
    assert time.monotonic() - start >= 0.4


def test_release_keeps_lock_of_another_process(tmp_path):
    lock = instance.acquire(tmp_path)
    path = tmp_path / LOCK_FILENAME
    path.write_text(json.dumps({"pid": os.getpid() + 1, "port": 1}))
    lock.release()
    assert path.exists()


def test_ping_ignores_other_servers(tmp_path):
    assert instance.ping(_free_port()) is False
