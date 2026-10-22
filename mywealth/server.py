"""Local web server: static UI + JSON API (standard library only).

Security / privacy:
- listens ONLY on 127.0.0.1, so it can't be reached from other devices on the network;
- rejects requests whose Host header isn't 127.0.0.1/localhost (DNS-rebinding protection);
- every /api call requires the random per-run token (X-MyWealth-Token header) that is
  injected into the page: other websites open in the browser can neither read nor change data;
- no external resources (CDNs, fonts, analytics): the page is served entirely from here.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import secrets
import socket
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import __version__, settings
from .db import Database
from .instance import APP_ID, PING_PATH

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent / "web"
TOKEN_HEADER = "X-MyWealth-Token"
TOKEN_PLACEHOLDER = "__MYWEALTH_TOKEN__"
ALLOWED_HOSTS = ("127.0.0.1", "localhost")
MAX_BODY = 1_000_000


@dataclass
class AppContext:
    db: Database
    data_dir: Path
    demo: bool = False
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class MyWealthServer(ThreadingHTTPServer):
    # Non-daemon request threads: server_close() waits for them, so a save in progress
    # always completes before the process exits.
    daemon_threads = False

    # On Windows SO_REUSEADDR lets a second socket bind a port that is already in use,
    # so two instances would silently share it. Ask for exclusive use instead.
    allow_reuse_address = not hasattr(socket, "SO_EXCLUSIVEADDRUSE")

    def __init__(self, address: tuple[str, int], ctx: AppContext):
        super().__init__(address, Handler)
        self.ctx = ctx

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    @property
    def port(self) -> int:
        return self.server_address[1]

    def request_shutdown(self) -> None:
        # shutdown() blocks until serve_forever() returns: never call it from a request thread.
        threading.Thread(target=self.shutdown, daemon=True).start()


def make_server(ctx: AppContext, port: int, attempts: int = 20) -> MyWealthServer:
    """Bind 127.0.0.1 on `port`, or the next free one. Port 0 picks any free port."""
    last_error: OSError | None = None
    for p in range(port, port + attempts) if port else [0]:
        try:
            return MyWealthServer(("127.0.0.1", p), ctx)
        except OSError as e:
            last_error = e
    raise OSError(f"No free port between {port} and {port + attempts - 1}") from last_error


class Handler(BaseHTTPRequestHandler):
    server: MyWealthServer
    server_version = "myWealth"
    sys_version = ""

    def log_message(self, format, *args):  # never log requests: URLs may carry user data
        pass

    @property
    def ctx(self) -> AppContext:
        return self.server.ctx

    # ---------------------------------------------------------------- helpers

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        return host in ALLOWED_HOSTS

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data) -> None:
        self._send(status, json.dumps(data).encode(), "application/json; charset=utf-8")

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "Richiesta non valida.") from None
        if n > MAX_BODY:
            raise ApiError(413, "Richiesta troppo grande.")
        raw = self.rfile.read(n) if n > 0 else b""
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            raise ApiError(400, "JSON non valido.") from None
        if not isinstance(data, dict):
            raise ApiError(400, "JSON non valido.")
        return data

    # --------------------------------------------------------------- dispatch

    def _handle(self, method: str) -> None:
        if not self._host_ok():
            self._send(403, b"Forbidden", "text/plain; charset=utf-8")
            return
        path = urlparse(self.path).path
        try:
            if path.startswith("/api/"):
                token = self.headers.get(TOKEN_HEADER, "")
                if not secrets.compare_digest(token.encode(), self.ctx.token.encode()):
                    raise ApiError(403, "Token non valido: ricarica la pagina.")
                self._api(method, path)
            elif method == "GET" and path == PING_PATH:
                self._json(200, {"app": APP_ID})
            elif method == "GET":
                self._static(path)
            else:
                raise ApiError(405, "Metodo non consentito.")
        except ApiError as e:
            self._json(e.status, {"error": str(e)})
        except Exception:
            log.exception("Unexpected error on %s %s", method, path)
            self._json(500, {"error": "Errore imprevisto: vedi il log."})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    # ----------------------------------------------------------------- static

    def _static(self, path: str) -> None:
        if path in ("/", "/index.html"):
            html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
            html = html.replace(TOKEN_PLACEHOLDER, self.ctx.token)
            self._send(200, html.encode(), "text/html; charset=utf-8")
            return
        root = WEB_DIR.resolve()
        target = (root / path.lstrip("/")).resolve()
        if root not in target.parents or not target.is_file():
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith(("javascript", "svg+xml")):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    # -------------------------------------------------------------------- api

    def _api(self, method: str, path: str) -> None:
        route = path[len("/api/"):].rstrip("/")

        if method == "GET" and route == "status":
            self._json(
                200,
                {
                    "version": __version__,
                    "demo": self.ctx.demo,
                    "data_dir": str(self.ctx.data_dir),
                    "schema_version": self.ctx.db.schema_version(),
                },
            )
            return

        if route == "settings":
            if method == "GET":
                self._json(200, settings.load(self.ctx.db))
                return
            if method == "PUT":
                try:
                    self._json(200, settings.update(self.ctx.db, self._body()))
                except settings.SettingsError as e:
                    raise ApiError(400, str(e)) from None
                return

        if method == "POST" and route == "shutdown":
            self._json(200, {"ok": True})
            log.info("Shutdown requested from the UI")
            self.server.request_shutdown()
            return

        raise ApiError(404, "Endpoint non trovato.")
