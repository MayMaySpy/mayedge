"""Refuse browser traffic that did not come from the desk's own page.

There is no login (ADR 0005), so the browser is the weak point: any site open in
it can reach a loopback or tailnet port. Two checks close that:

- Host must be a name the desk is served under. A DNS-rebinding page arrives
  with its own hostname and is turned away.
- Origin, on a WebSocket or a state-changing request, must be the desk's own
  page or a configured dev origin. Browsers always send it on those requests.
  A request with no Origin is not a browser and passes.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocketClose

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _hostname(netloc: str) -> str:
    """``host`` from ``host:port``; brackets kept on an IPv6 literal."""
    netloc = netloc.strip().lower()
    if netloc.startswith("["):
        return netloc.split("]", 1)[0] + "]"
    return netloc.rsplit(":", 1)[0] if ":" in netloc else netloc


def host_allowed(host_header: str, allowed: Iterable[str]) -> bool:
    name = _hostname(host_header)
    if not name:
        return False
    for pattern in allowed:
        pattern = pattern.strip().lower()
        if pattern == "*" or pattern == name:
            return True
        if pattern.startswith("*.") and name.endswith(pattern[1:]):
            return True
    return False


def origin_allowed(origin: str, served_as: Iterable[str], extra_origins: Iterable[str]) -> bool:
    """True when ``origin`` is the page this server itself was reached as."""
    origin = origin.strip().lower().rstrip("/")
    if origin in {o.strip().lower().rstrip("/") for o in extra_origins}:
        return True
    netloc = urlsplit(origin).netloc
    if not netloc:
        return False
    return netloc in {h.strip().lower() for h in served_as if h}


class BrowserGuard:
    def __init__(
        self,
        app: ASGIApp,
        *,
        allowed_hosts: Iterable[str],
        allowed_origins: Iterable[str],
    ) -> None:
        self.app = app
        self.allowed_hosts = tuple(allowed_hosts)
        self.allowed_origins = tuple(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]
        if kind not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers: dict[str, str] = {}
        for raw_key, raw_value in scope.get("headers") or []:
            headers.setdefault(raw_key.decode("latin-1").lower(), raw_value.decode("latin-1"))
        host = headers.get("host", "")
        if not host_allowed(host, self.allowed_hosts):
            await self._refuse(scope, receive, send, 400, "Host not allowed")
            return
        origin = headers.get("origin")
        checked = kind == "websocket" or scope.get("method", "GET") not in _SAFE_METHODS
        if checked and origin is not None:
            # A proxy that rewrites Host reports the page's name in X-Forwarded-Host.
            served_as = (host, headers.get("x-forwarded-host", ""))
            if not origin_allowed(origin, served_as, self.allowed_origins):
                await self._refuse(scope, receive, send, 403, "Origin not allowed")
                return
        await self.app(scope, receive, send)

    @staticmethod
    async def _refuse(
        scope: Scope, receive: Receive, send: Send, status: int, reason: str
    ) -> None:
        if scope["type"] == "websocket":
            await WebSocketClose(code=1008, reason=reason)(scope, receive, send)
            return
        await PlainTextResponse(reason, status_code=status)(scope, receive, send)
