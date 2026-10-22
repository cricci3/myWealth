"""Windows shortcuts: Start menu, desktop and (optional) start at login.

The .lnk files are written by PowerShell through `WScript.Shell` (no extra
dependency). They point to `mywealth-gui.exe` in the project's environment, with the
project folder as working directory and the app icon. If that executable is missing
(or blocked by AppLocker/WDAC), `vbs=True` makes them launch a small VBScript that runs
`uv run --project <folder> mywealth-gui` with a hidden window instead.

These functions are run only by the user (`--install-shortcuts`, Settings).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import paths
from .errors import AppError

APP_NAME = "myWealth"
PROJECT_DIR = Path(__file__).resolve().parents[1]
ICON = Path(__file__).resolve().parent / "web" / "icon.ico"
VBS_NAME = "avvia-mywealth.vbs"

_PS_CREATE = (
    "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:MW_LNK);"
    "$s.TargetPath = $env:MW_TARGET; $s.Arguments = $env:MW_ARGS;"
    "$s.WorkingDirectory = $env:MW_WD; $s.IconLocation = $env:MW_ICON;"
    "$s.Description = 'myWealth - finanze personali'; $s.Save()"
)


class ShortcutError(AppError):
    pass


def is_supported() -> bool:
    return sys.platform.startswith("win")


def _special(name: str) -> Path:
    appdata = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    programs = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    if name == "start_menu":
        return programs
    if name == "startup":
        return programs / "Startup"
    if name == "desktop":
        return Path(os.environ.get("USERPROFILE") or Path.home()) / "Desktop"
    raise ValueError(name)


def locations() -> dict[str, Path]:
    return {k: _special(k) / f"{APP_NAME}.lnk" for k in ("start_menu", "desktop", "startup")}


def gui_executable() -> Path:
    return Path(sys.executable).parent / ("mywealth-gui.exe" if is_supported() else "mywealth-gui")


def _vbs(data_dir: Path) -> Path:
    uv = shutil.which("uv")
    if not uv:
        raise ShortcutError("uv non trovato nel PATH: impossibile creare il collegamento alternativo.")
    script = data_dir / VBS_NAME
    data_dir.mkdir(parents=True, exist_ok=True)
    cmd = f'""{uv}"" run --project ""{PROJECT_DIR}"" mywealth-gui'
    script.write_text(f'CreateObject("WScript.Shell").Run "{cmd}", 0, False\r\n', encoding="utf-8")
    return script


def target(vbs: bool = False, data_dir: Path | None = None) -> tuple[str, str]:
    """(program, arguments) the shortcuts launch."""
    exe = gui_executable()
    if not vbs and exe.exists():
        return str(exe), ""
    script = _vbs(data_dir or paths.data_dir())
    wscript = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "wscript.exe"
    return str(wscript), f'"{script}"'


def create(kind: str, vbs: bool = False, data_dir: Path | None = None) -> Path:
    if not is_supported():
        raise ShortcutError("I collegamenti sono disponibili solo su Windows.")
    lnk = locations()[kind]
    lnk.parent.mkdir(parents=True, exist_ok=True)
    program, args = target(vbs, data_dir)
    env = {**os.environ, "MW_LNK": str(lnk), "MW_TARGET": program, "MW_ARGS": args, "MW_WD": str(PROJECT_DIR),
           "MW_ICON": f"{ICON},0"}
    res = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _PS_CREATE],
        env=env, capture_output=True, text=True, timeout=60,
        creationflags=0x08000000 if is_supported() else 0,
    )
    if res.returncode != 0 or not lnk.exists():
        raise ShortcutError(f"Collegamento non creato: {(res.stderr or res.stdout).strip()[:300]}")
    return lnk


def remove(kind: str) -> bool:
    lnk = locations()[kind]
    if lnk.exists():
        lnk.unlink()
        return True
    return False


def status() -> dict:
    return {"supported": is_supported(), **{k: p.exists() for k, p in locations().items()},
            "gui_executable": gui_executable().exists()}


def install(desktop: bool, vbs: bool = False) -> list[Path]:
    made = [create("start_menu", vbs)]
    if desktop:
        made.append(create("desktop", vbs))
    return made


def uninstall() -> list[str]:
    return [k for k in ("start_menu", "desktop", "startup") if remove(k)]
