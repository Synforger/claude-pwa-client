"""Count the requests an app receives by where they come from, and log each new count worth a line.

A request is counted under one tuple: (app name, method, route template, Host, Origin, Sec-Fetch-Site). Only those
header values and the template of the matched route are read; the body, the query string, the real path, path
parameters, cookies and every other header are never looked at, and no value is kept as sent unless it has the shape
described next. A value outside its shape is counted as `(malformed)`, an absent one as `(none)`.

The request is counted at its first send (the response start, the WebSocket accept or close), so a WebSocket and a
response that never ends are counted without waiting for the end; a request that ends before it sends is counted at
its end. Responses, exceptions, streams and WebSockets pass through unchanged: an error inside the counting leaves one
warning and the request goes on.

Used by `backend/main.py`, which installs it on the main app and on the page app. The label rules, the counter and the
middleware are kept in one file while they are this small and change together.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from typing import Any, NamedTuple

from starlette.routing import Mount
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

APP_NAME_MAIN = "main"
APP_NAME_PAGE = "page"

# How many different tuples are kept; a tuple past this is counted in the one overflow tuple.
MAX_PAIR_COUNT = 1000
# A header value longer than this is not kept (a Host or Origin is far shorter).
MAX_HEADER_LENGTH = 200

NONE_LABEL = "(none)"
MALFORMED_LABEL = "(malformed)"
UNMATCHED_LABEL = "(unmatched)"
OVERFLOW_LABEL = "(overflow)"
MOUNT_LABEL = "(mount)"

WEBSOCKET_METHOD = "WS"
HTTP_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "DELETE", "CONNECT", "OPTIONS", "TRACE", "PATCH"})
FETCH_SITES = frozenset({"same-origin", "same-site", "cross-site", "none"})

_HOST_PATTERN = r"(?:[A-Za-z0-9._\-]+|\[[0-9A-Fa-f:.]+\])(?::[0-9]{1,5})?"
_HOST_RE = re.compile(_HOST_PATTERN)
_ORIGIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://" + _HOST_PATTERN)

_HEADER_NAMES = (b"host", b"origin", b"sec-fetch-site")


class RequestOrigin(NamedTuple):
    """One counted tuple; every field is a label, never a raw request value."""

    app: str
    method: str
    template: str
    host: str
    origin: str
    fetch_site: str


OVERFLOW_ORIGIN = RequestOrigin(*([OVERFLOW_LABEL] * len(RequestOrigin._fields)))


def host_label(raw: bytes | None) -> str:
    """The Host header as host[:port] in lower case, `(none)` when absent, `(malformed)` outside the shape."""
    return _shaped_label(raw, _HOST_RE)


def origin_label(raw: bytes | None) -> str:
    """The Origin header as scheme://host[:port] in lower case or `null`; `(none)` when absent."""
    if raw == b"null":
        return "null"
    return _shaped_label(raw, _ORIGIN_RE)


def fetch_site_label(raw: bytes | None) -> str:
    """The Sec-Fetch-Site header when it is one of the four words the specification defines."""
    if raw is None:
        return NONE_LABEL
    if len(raw) > MAX_HEADER_LENGTH or not raw.isascii():
        return MALFORMED_LABEL
    value = raw.decode("ascii")
    return value if value in FETCH_SITES else MALFORMED_LABEL


def method_label(scope: Scope) -> str:
    """`WS` for a WebSocket, else the request method when it is a standard one."""
    if scope["type"] == "websocket":
        return WEBSOCKET_METHOD
    method = scope.get("method")
    return method if method in HTTP_METHODS else MALFORMED_LABEL


def route_label(scope: Scope) -> str:
    """The template of the route that handled the request, read from the scope after routing.

    The real path is never used: a request that matched no route is `(unmatched)`, and one handled by a mount is the
    mount's name.
    """
    for route in _matched_routes(scope):
        label = _template_or_mount_name(route)
        if label:
            return label
    return UNMATCHED_LABEL


def _matched_routes(scope: Scope) -> Iterator[Any]:
    """The route-like objects that may name the matched route, most exact first; the router is searched last."""
    route = scope.get("route")
    context = scope.get("fastapi", {}).get("effective_route_context")
    # FastAPI keeps an included router's routes unprefixed and holds the prefixed one in this context. The context is
    # used only when it belongs to the matched route, so a stale one is not read.
    if context is not None and (
        route is None
        or route is getattr(context, "original_route", None)
        or route is getattr(context, "starlette_route", None)
    ):
        yield getattr(context, "starlette_route", None)
        yield context
    yield route
    yield _route_of_endpoint(scope)


def _shaped_label(raw: bytes | None, shape: re.Pattern[str]) -> str:
    if raw is None:
        return NONE_LABEL
    if len(raw) > MAX_HEADER_LENGTH or not raw.isascii():
        return MALFORMED_LABEL
    value = raw.decode("ascii")
    return value.lower() if shape.fullmatch(value) is not None else MALFORMED_LABEL


def _template_or_mount_name(route: Any) -> str | None:
    if route is None:
        return None
    if isinstance(route, Mount):
        return route.name or MOUNT_LABEL
    return getattr(route, "path_format", None) or None


def _route_of_endpoint(scope: Scope) -> Any:
    """The route of the scope's router whose endpoint or mounted app is the one routing chose.

    Starlette's own routes and mounts reach the scope as an `endpoint` only; FastAPI's router does not put the route
    itself there.
    """
    endpoint = scope.get("endpoint")
    if endpoint is None:
        return None
    for route in getattr(scope.get("router"), "routes", ()):
        if getattr(route, "app", None) is endpoint or getattr(route, "endpoint", None) is endpoint:
            return route
    return None


def request_origin(app_name: str, scope: Scope) -> RequestOrigin:
    """The tuple a request is counted under, from its scope after routing."""
    headers: dict[bytes, bytes] = {}
    for name, value in scope.get("headers") or ():
        if name in _HEADER_NAMES and name not in headers:
            headers[name] = value
    return RequestOrigin(
        app=app_name,
        method=method_label(scope),
        template=route_label(scope),
        host=host_label(headers.get(b"host")),
        origin=origin_label(headers.get(b"origin")),
        fetch_site=fetch_site_label(headers.get(b"sec-fetch-site")),
    )


class RequestOriginCounter:
    """Counts tuples and logs one INFO line when a tuple first appears and when its count reaches a power of ten.

    Used from the event loop only, so it takes no lock.
    """

    def __init__(self, *, max_pair_count: int = MAX_PAIR_COUNT) -> None:
        self._max_pair_count = max_pair_count
        self._counts: dict[RequestOrigin, int] = {}
        self._overflow_count = 0
        self._is_failure_logged = False

    def add(self, origin: RequestOrigin) -> int:
        """Count one request under `origin` (the overflow tuple when the limit is reached); returns its count."""
        if origin not in self._counts and len(self._counts) >= self._max_pair_count:
            self._overflow_count += 1
            count = self._overflow_count
            origin = OVERFLOW_ORIGIN
        else:
            count = self._counts.get(origin, 0) + 1
            self._counts[origin] = count
        if str(count).rstrip("0") == "1":
            logger.info(
                "request origin: app=%s method=%s template=%s host=%s origin=%s sec_fetch_site=%s count=%d",
                *origin, count,
            )
        return count

    def counts(self) -> dict[RequestOrigin, int]:
        """A copy of the counts, the overflow tuple included when it has any."""
        counts = dict(self._counts)
        if self._overflow_count:
            counts[OVERFLOW_ORIGIN] = self._overflow_count
        return counts

    def warn_failure_once(self, error: Exception) -> None:
        """Log a failure of the counting the first time only, so a repeating one does not fill the log."""
        if self._is_failure_logged:
            return
        self._is_failure_logged = True
        logger.warning("request origin: counting failed, requests go on unchanged", exc_info=error)


# One counter for the process, so the limit on tuples holds for the main app and the page app together.
_process_counter = RequestOriginCounter()


class RequestOriginMiddleware:
    """Pure ASGI middleware: counts each HTTP and WebSocket request once and forwards everything unchanged."""

    def __init__(self, app: ASGIApp, *, app_name: str, counter: RequestOriginCounter | None = None) -> None:
        self.app = app
        self._app_name = app_name
        self._counter = counter if counter is not None else _process_counter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        is_counted = False

        async def send_counting(message: Message) -> None:
            nonlocal is_counted
            if not is_counted:
                is_counted = True
                self._count(scope)
            await send(message)

        try:
            await self.app(scope, receive, send_counting)
        finally:
            if not is_counted:
                self._count(scope)

    def _count(self, scope: Scope) -> None:
        try:
            self._counter.add(request_origin(self._app_name, scope))
        except Exception as error:  # the counting must never fail a request; it is logged once instead
            self._counter.warn_failure_once(error)


def install(app: Any, *, app_name: str) -> None:
    """Register the middleware on a FastAPI app (called from `backend/main.py` for each app)."""
    app.add_middleware(RequestOriginMiddleware, app_name=app_name)


__all__ = [
    "APP_NAME_MAIN",
    "APP_NAME_PAGE",
    "RequestOrigin",
    "RequestOriginCounter",
    "RequestOriginMiddleware",
    "install",
    "request_origin",
]
