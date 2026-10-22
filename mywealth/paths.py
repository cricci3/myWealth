"""Where the user's data lives.

  - Windows:   %APPDATA%\\myWealth\\
  - elsewhere: ~/.mywealth/

Override with the MYWEALTH_DATA_DIR environment variable. The folder is kept outside the
repository so the data never ends up in git or in front of tools working on the code.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ENV_DATA_DIR = "MYWEALTH_DATA_DIR"
DB_FILENAME = "mywealth.db"
LOCK_FILENAME = "mywealth.lock"
LOGS_DIRNAME = "logs"


def data_dir() -> Path:
    override = os.environ.get(ENV_DATA_DIR)
    if override:
        return Path(override).expanduser()
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "myWealth"
    return Path.home() / ".mywealth"
