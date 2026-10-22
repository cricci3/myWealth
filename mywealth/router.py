"""Tiny router for the JSON API: `@routes.get("accounts/<id>")` style registrations."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from .errors import ValidationError


@dataclass
class Request:
    method: str
    params: dict[str, int | str]
    query: dict[str, str]
    _body: Callable[[], dict] = field(repr=False)
    _raw: Callable[[], bytes] = field(repr=False, default=lambda: b"")
    headers: dict[str, str] = field(default_factory=dict)

    def body(self) -> dict:
        return self._body()

    def raw(self) -> bytes:
        return self._raw()

    def q(self, name: str, default: str | None = None) -> str | None:
        value = self.query.get(name)
        return value if value not in (None, "") else default

    def q_int(self, name: str, default: int | None = None) -> int | None:
        value = self.q(name)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            raise ValidationError(f"Parametro '{name}' non valido.") from None


@dataclass
class Response:
    """Non-JSON response (file downloads)."""

    body: bytes
    content_type: str
    filename: str | None = None


Handler = Callable[..., object]


class Router:
    def __init__(self) -> None:
        self._routes: list[tuple[str, re.Pattern, Handler]] = []

    def add(self, method: str, pattern: str, func: Handler) -> None:
        # <name> matches an integer id, <name:str> any path segment
        def repl(m: re.Match) -> str:
            name, _, kind = m.group(1).partition(":")
            return f"(?P<{name}>[^/]+)" if kind == "str" else f"(?P<{name}>\\d+)"

        regex = re.compile("^" + re.sub(r"<([^>]+)>", repl, pattern) + "$")
        self._routes.append((method, regex, func))

    def route(self, method: str, pattern: str):
        def deco(func: Handler) -> Handler:
            self.add(method, pattern, func)
            return func

        return deco

    def get(self, pattern: str):
        return self.route("GET", pattern)

    def post(self, pattern: str):
        return self.route("POST", pattern)

    def put(self, pattern: str):
        return self.route("PUT", pattern)

    def delete(self, pattern: str):
        return self.route("DELETE", pattern)

    def match(self, method: str, path: str) -> tuple[Handler, dict] | None:
        for m, regex, func in self._routes:
            if m != method:
                continue
            found = regex.match(path)
            if found:
                params = {k: (int(v) if v.isdigit() else v) for k, v in found.groupdict().items()}
                return func, params
        return None
