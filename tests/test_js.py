"""Runs the JavaScript tests of the smartphone PWA and of the desktop decryption
(tests/js, Node's built-in test runner and Web Crypto). Skipped when Node isn't installed."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_javascript_suite():
    files = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "tests" / "js").glob("*.test.mjs"))
    assert files
    res = subprocess.run(["node", "--test", *files], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                         timeout=120)
    assert res.returncode == 0, res.stdout[-4000:] + res.stderr[-2000:]
