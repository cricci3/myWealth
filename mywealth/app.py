"""Entry points.

    mywealth                        -> start the local server and open the UI (app window)
    mywealth --demo                 -> temporary database with synthetic data, no network
    mywealth --port 9000 --no-browser
    mywealth --install-shortcuts    -> Start menu (and optionally desktop) shortcuts
    mywealth --uninstall-shortcuts
    mywealth-gui                    -> same as `mywealth`, without a console window
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import __version__, instance, launcher, paths
from .db import Database, SchemaTooNewError
from .server import AppContext, make_server

log = logging.getLogger("mywealth")

DEFAULT_PORT = 8777
IDLE_CHECK_SECONDS = 30


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="mywealth", description="myWealth: finanze personali in locale.")
    parser.add_argument("--port", type=int, default=None,
                        help=f"porta locale (default: quella delle Impostazioni, {DEFAULT_PORT})")
    parser.add_argument("--no-browser", action="store_true", help="non aprire la finestra dell'app")
    parser.add_argument("--demo", action="store_true", help="dati sintetici in un database temporaneo, nessuna rete")
    parser.add_argument("--install-shortcuts", action="store_true",
                        help="crea il collegamento nel menu Start (e, se richiesto, sul desktop)")
    parser.add_argument("--uninstall-shortcuts", action="store_true", help="rimuove i collegamenti di myWealth")
    desk = parser.add_mutually_exclusive_group()
    desk.add_argument("--desktop", dest="desktop", action="store_true", default=None,
                      help="con --install-shortcuts: crea anche il collegamento sul desktop")
    desk.add_argument("--no-desktop", dest="desktop", action="store_false", help="con --install-shortcuts: niente desktop")
    parser.add_argument("--vbs", action="store_true",
                        help="con --install-shortcuts: avvia tramite uno script VBS (se mywealth-gui è bloccato)")
    parser.add_argument("--version", action="version", version=f"myWealth {__version__}")
    return parser.parse_args(argv)


def setup_logging(data_dir: Path, gui: bool) -> logging.Handler:
    """Console mode logs to stderr; GUI mode (no console) to rotating files in <data dir>/logs."""
    log.setLevel(logging.INFO)
    if gui or sys.stderr is None:
        logs = data_dir / paths.LOGS_DIRNAME
        logs.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            logs / "mywealth.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    else:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(handler)
    return handler


def shortcuts_command(args: argparse.Namespace) -> int:
    """--install-shortcuts / --uninstall-shortcuts (run by the user, see SPEC §13)."""
    from . import shortcuts

    if not shortcuts.is_supported():
        print("I collegamenti sono disponibili solo su Windows.")
        return 1
    try:
        if args.uninstall_shortcuts:
            removed = shortcuts.uninstall()
            print("Collegamenti rimossi: " + (", ".join(removed) if removed else "nessuno"))
            return 0
        desktop = args.desktop
        if desktop is None:
            answer = input("Creare anche il collegamento sul desktop? [s/N] ") if sys.stdin and sys.stdin.isatty() else ""
            desktop = answer.strip().lower() in ("s", "si", "sì", "y", "yes")
        for lnk in shortcuts.install(desktop, vbs=args.vbs):
            print(f"Creato: {lnk}")
        print("Ora puoi aprire myWealth dal menu Start (scrivi \"myWealth\" dopo aver premuto il tasto Windows).")
        return 0
    except shortcuts.ShortcutError as e:
        print(f"Errore: {e}")
        return 1


def run(argv: list[str] | None = None, gui: bool = False) -> int:
    args = parse_args(argv)
    if args.install_shortcuts or args.uninstall_shortcuts:
        return shortcuts_command(args)
    if args.demo:
        # Fresh throw-away folder: the real data is never touched, and the demo never
        # collides with a running real instance (different lock file).
        data_dir = Path(tempfile.mkdtemp(prefix="mywealth-demo-"))
    else:
        data_dir = paths.data_dir()
    handler = setup_logging(data_dir, gui)

    try:
        return _serve(args, data_dir)
    except Exception:
        log.exception("myWealth stopped because of an unexpected error")
        return 1
    finally:
        log.removeHandler(handler)
        handler.close()
        if args.demo:
            shutil.rmtree(data_dir, ignore_errors=True)


def _prefs(db: Database) -> dict:
    from . import settings

    try:
        return settings.load(db)
    except Exception:  # unreadable/new database: defaults
        return dict(settings.DEFAULTS)


def _serve(args: argparse.Namespace, data_dir: Path) -> int:
    lock = instance.acquire(data_dir)
    if isinstance(lock, int):
        url = f"http://127.0.0.1:{lock}/"
        log.info("myWealth is already running at %s: opening it.", url)
        if not args.no_browser:
            choice = _prefs(Database(data_dir / paths.DB_FILENAME))["app_browser"]
            launcher.open_window(url, data_dir, choice)
        return 0

    try:
        db = Database(data_dir / paths.DB_FILENAME)
        try:
            db.migrate()
        except SchemaTooNewError as e:
            log.error("%s", e)
            return 1
        ctx = AppContext(db=db, data_dir=data_dir, demo=args.demo)
        startup(ctx)
        prefs = _prefs(db)
        httpd = make_server(ctx, args.port if args.port is not None else prefs["port"])
        lock.set_port(httpd.port)
        url = f"http://127.0.0.1:{httpd.port}/"
        log.info("myWealth %s running at %s", __version__, url)
        if args.demo:
            log.info("DEMO mode: temporary database, no network calls.")
        else:
            log.info("Data folder: %s", data_dir)
        log.info("Use the 'Esci' button in the app (or Ctrl+C) to stop.")
        if not args.no_browser:
            threading.Timer(0.3, launcher.open_window, (url, data_dir, prefs["app_browser"])).start()
            # Without a console the only ways out are "Esci" and closing the window: stop
            # when the page has been gone for a while. Not with --no-browser (development).
            watch_idle(ctx, httpd)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()  # waits for in-flight requests to finish
        log.info("myWealth stopped.")
        return 0
    finally:
        lock.release()


def watch_idle(ctx: AppContext, httpd, check_every: float = IDLE_CHECK_SECONDS) -> threading.Thread:
    """Shut down when no page has sent a heartbeat for `idle_minutes` (0 = never)."""
    from . import settings

    def loop() -> None:
        while not ctx.stopping.wait(check_every):
            minutes = settings.get(ctx.db, "idle_minutes")
            if minutes and time.monotonic() - ctx.last_heartbeat > minutes * 60:
                log.info("No open window for %d minutes: stopping.", minutes)
                httpd.request_shutdown()
                return

    t = threading.Thread(target=loop, name="idle-watch", daemon=True)
    t.start()
    return t


def startup(ctx: AppContext) -> None:
    """Data jobs run at every start: backup, demo data, interest, exchange rates."""
    from . import api, archive, demo, savings, settings

    if not ctx.demo and not archive.is_empty(ctx.db):
        try:
            name = archive.create_backup(ctx.db, ctx.data_dir, "auto")
            log.info("Backup saved: %s", name)
        except Exception:
            log.exception("Automatic backup failed")
    if ctx.demo:
        demo.seed(ctx.db)
        api.refresh_market(ctx, wait=True)  # synthetic rates, no network
    try:
        created = savings.generate(ctx.db)
        if created:
            log.info("Savings interest generated for %d month(s).", len(created))
    except Exception:
        log.exception("Savings interest generation failed")
    if ctx.demo:
        return
    prefs = settings.load(ctx.db)
    if prefs["fx_auto_refresh"] and not prefs["offline_mode"]:
        api.refresh_market(ctx)  # background: the UI is usable while rates download


def main() -> int:
    return run(sys.argv[1:])


def gui_main() -> int:
    return run(sys.argv[1:], gui=True)


if __name__ == "__main__":
    raise SystemExit(main())
