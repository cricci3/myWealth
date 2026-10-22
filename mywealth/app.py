"""Entry points.

    mywealth                        -> start the local server and open the UI in the browser
    mywealth --demo                 -> temporary database with synthetic data, no network
    mywealth --port 9000 --no-browser
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
import webbrowser
from pathlib import Path

from . import __version__, instance, paths
from .db import Database, SchemaTooNewError
from .server import AppContext, make_server

log = logging.getLogger("mywealth")

DEFAULT_PORT = 8777


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="mywealth", description="myWealth: finanze personali in locale.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"porta locale (default {DEFAULT_PORT})")
    parser.add_argument("--no-browser", action="store_true", help="non aprire il browser")
    parser.add_argument("--demo", action="store_true", help="dati sintetici in un database temporaneo, nessuna rete")
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


def open_browser(url: str) -> None:
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()


def run(argv: list[str] | None = None, gui: bool = False) -> int:
    args = parse_args(argv)
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


def _serve(args: argparse.Namespace, data_dir: Path) -> int:
    lock = instance.acquire(data_dir)
    if isinstance(lock, int):
        url = f"http://127.0.0.1:{lock}/"
        log.info("myWealth is already running at %s: opening it.", url)
        if not args.no_browser:
            webbrowser.open(url)
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
        httpd = make_server(ctx, args.port)
        lock.set_port(httpd.port)
        url = f"http://127.0.0.1:{httpd.port}/"
        log.info("myWealth %s running at %s", __version__, url)
        if args.demo:
            log.info("DEMO mode: temporary database, no network calls.")
        else:
            log.info("Data folder: %s", data_dir)
        log.info("Use the 'Esci' button in the app (or Ctrl+C) to stop.")
        if not args.no_browser:
            open_browser(url)
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


def startup(ctx: AppContext) -> None:
    """Data jobs run at every start: demo data, exchange rates."""
    from . import api, demo, savings, settings

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
