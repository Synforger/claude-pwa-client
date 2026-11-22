"""Request origin counting: the labels, the route template read after routing, when a request is counted, the limit on
tuples, the log lines, and that responses, exceptions, streams and WebSockets pass through unchanged."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI, WebSocket

from backend.observability.request_origin import (
    MAX_PAIR_COUNT,
    OVERFLOW_ORIGIN,
    RequestOrigin,
    RequestOriginCounter,
    RequestOriginMiddleware,
    fetch_site_label,
    host_label,
    method_label,
    origin_label,
)
from backend.tests.async_run import run

LOGGER_NAME = "backend.observability.request_origin"

Message = dict[str, Any]
Headers = list[tuple[bytes, bytes]]


def _http_scope(path: str, *, method: str = "GET", headers: Headers | None = None, query: bytes = b"") -> Message:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query,
        "root_path": "",
        "headers": headers or [],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8765),
    }


def _websocket_scope(path: str, *, headers: Headers | None = None) -> Message:
    return {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "scheme": "ws",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers or [],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8765),
        "subprotocols": [],
    }


async def _drive(app: Callable[..., Awaitable[None]], scope: Message) -> list[Message]:
    """Run one request through `app` and return what it sent; the client sends its request, then disconnects."""
    incoming: list[Message] = (
        [{"type": "websocket.connect"}] if scope["type"] == "websocket"
        else [{"type": "http.request", "body": b"", "more_body": False}]
    )
    disconnect = "websocket.disconnect" if scope["type"] == "websocket" else "http.disconnect"
    sent: list[Message] = []

    async def receive() -> Message:
        return incoming.pop(0) if incoming else {"type": disconnect, "code": 1000}

    async def send(message: Message) -> None:
        sent.append(message)

    await app(scope, receive, send)
    return sent


def _build_app(counter: RequestOriginCounter) -> FastAPI:
    app = FastAPI()
    router = APIRouter(prefix="/api")

    @router.get("/items/{item_id}")
    async def read_item(item_id: str) -> dict[str, str]:
        return {"id": item_id}

    @router.websocket("/live/{room}")
    async def live(websocket: WebSocket, room: str) -> None:
        await websocket.accept()
        await websocket.close()

    @app.get("/direct/{name}")
    async def read_direct(name: str) -> dict[str, str]:
        return {"name": name}

    async def mounted(scope: Message, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.include_router(router)
    app.mount("/files", mounted, name="files")
    app.add_middleware(RequestOriginMiddleware, app_name="main", counter=counter)
    return app


def _status(sent: list[Message]) -> int:
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


# --- labels ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("raw", "label"), [
    (None, "(none)"),
    (b"localhost:8765", "localhost:8765"),
    (b"Machine.Tailnet.TS.net", "machine.tailnet.ts.net"),
    (b"[::1]:8765", "[::1]:8765"),
    (b"a" * 200, "a" * 200),
    (b"a" * 201, "(malformed)"),
    (b"", "(malformed)"),
    (b"two words", "(malformed)"),
    (b"host/path", "(malformed)"),
    (b"user@host", "(malformed)"),
    (b"host:port", "(malformed)"),
    ("ホスト".encode(), "(malformed)"),
])
def test_host_label(raw: bytes | None, label: str) -> None:
    assert host_label(raw) == label


@pytest.mark.parametrize(("raw", "label"), [
    (None, "(none)"),
    (b"null", "null"),
    (b"https://machine.tailnet.ts.net", "https://machine.tailnet.ts.net"),
    (b"http://localhost:5173", "http://localhost:5173"),
    (b"HTTPS://Example.COM", "https://example.com"),
    (b"https://example.com/path", "(malformed)"),
    (b"https://", "(malformed)"),
    (b"javascript:alert(1)", "(malformed)"),
    (b"https://example.com " + b"x" * 200, "(malformed)"),
])
def test_origin_label(raw: bytes | None, label: str) -> None:
    assert origin_label(raw) == label


@pytest.mark.parametrize(("raw", "label"), [
    (None, "(none)"),
    (b"same-origin", "same-origin"),
    (b"same-site", "same-site"),
    (b"cross-site", "cross-site"),
    (b"none", "none"),
    (b"Same-Origin", "(malformed)"),
    (b"elsewhere", "(malformed)"),
    (b"", "(malformed)"),
])
def test_fetch_site_label(raw: bytes | None, label: str) -> None:
    assert fetch_site_label(raw) == label


def test_fetch_site_none_the_word_is_not_the_absent_label() -> None:
    assert fetch_site_label(b"none") != fetch_site_label(None)


def test_method_label() -> None:
    assert method_label(_http_scope("/", method="PATCH")) == "PATCH"
    assert method_label(_http_scope("/", method="BREW")) == "(malformed)"
    assert method_label(_websocket_scope("/")) == "WS"


# --- the route template ---------------------------------------------------------------------------------------------


def test_included_router_route_is_counted_by_its_prefixed_template_and_not_by_its_id() -> None:
    counter = RequestOriginCounter()
    app = _build_app(counter)
    sent = run(_drive(app, _http_scope("/api/items/42", query=b"token=secret")))
    assert _status(sent) == 200
    assert [key.template for key in counter.counts()] == ["/api/items/{item_id}"]
    for forbidden in ("42", "token", "secret"):
        assert forbidden not in repr(counter.counts())


def test_a_route_of_the_app_itself_is_counted_by_its_template() -> None:
    counter = RequestOriginCounter()
    run(_drive(_build_app(counter), _http_scope("/direct/someone")))
    assert [key.template for key in counter.counts()] == ["/direct/{name}"]
    assert "someone" not in repr(counter.counts())


def test_a_method_the_route_does_not_serve_keeps_the_template() -> None:
    counter = RequestOriginCounter()
    sent = run(_drive(_build_app(counter), _http_scope("/api/items/42", method="POST")))
    assert _status(sent) == 405
    assert [(key.method, key.template) for key in counter.counts()] == [("POST", "/api/items/{item_id}")]


def test_websocket_of_an_included_router_is_counted_as_ws_by_its_template() -> None:
    counter = RequestOriginCounter()
    sent = run(_drive(_build_app(counter), _websocket_scope("/api/live/room-7")))
    assert [m["type"] for m in sent] == ["websocket.accept", "websocket.close"]
    assert [(key.method, key.template) for key in counter.counts()] == [("WS", "/api/live/{room}")]
    assert "room-7" not in repr(counter.counts())


def test_a_mount_is_counted_by_its_name_and_an_unknown_path_as_unmatched() -> None:
    counter = RequestOriginCounter()
    app = _build_app(counter)
    assert _status(run(_drive(app, _http_scope("/files/secret/report.pdf")))) == 200
    assert _status(run(_drive(app, _http_scope("/nowhere/private-name")))) == 404
    assert sorted(key.template for key in counter.counts()) == ["(unmatched)", "files"]
    for forbidden in ("secret", "report", "nowhere", "private-name"):
        assert forbidden not in repr(counter.counts())


def test_the_values_counted_are_the_three_headers_and_nothing_else_is_read() -> None:
    counter = RequestOriginCounter()
    headers = [
        (b"host", b"localhost:8765"),
        (b"origin", b"https://machine.tailnet.ts.net"),
        (b"sec-fetch-site", b"cross-site"),
        (b"cookie", b"session=cookie-value"),
        (b"authorization", b"Bearer bearer-value"),
    ]
    run(_drive(_build_app(counter), _http_scope("/api/items/42", headers=headers)))
    assert counter.counts() == {
        RequestOrigin(
            app="main",
            method="GET",
            template="/api/items/{item_id}",
            host="localhost:8765",
            origin="https://machine.tailnet.ts.net",
            fetch_site="cross-site",
        ): 1,
    }


def test_a_request_without_the_headers_is_counted_as_none() -> None:
    counter = RequestOriginCounter()
    run(_drive(_build_app(counter), _http_scope("/api/items/42")))
    (key,) = counter.counts()
    assert (key.host, key.origin, key.fetch_site) == ("(none)", "(none)", "(none)")


def test_values_outside_their_shape_are_counted_as_malformed() -> None:
    counter = RequestOriginCounter()
    headers = [(b"host", b"a b"), (b"origin", b"https://x/y"), (b"sec-fetch-site", b"sideways")]
    run(_drive(_build_app(counter), _http_scope("/api/items/42", headers=headers)))
    (key,) = counter.counts()
    assert (key.host, key.origin, key.fetch_site) == ("(malformed)",) * 3


# --- when a request is counted --------------------------------------------------------------------------------------


def _blocking_app(first_message: Message) -> tuple[Callable[..., Awaitable[None]], asyncio.Event]:
    """An app that sends one message and then waits until released; sets nothing itself."""
    release = asyncio.Event()

    async def app(scope: Message, receive: Any, send: Any) -> None:
        await send(first_message)
        await release.wait()

    return app, release


def _count_while_the_request_is_open(scope: Message, first_message: Message) -> dict[RequestOrigin, int]:
    async def count_open() -> dict[RequestOrigin, int]:
        counter = RequestOriginCounter()
        app, release = _blocking_app(first_message)
        first_sent = asyncio.Event()

        async def receive() -> Message:
            return {"type": "http.disconnect"}

        async def send(message: Message) -> None:
            first_sent.set()

        task = asyncio.ensure_future(RequestOriginMiddleware(app, app_name="main", counter=counter)(scope, receive, send))
        await asyncio.wait_for(first_sent.wait(), timeout=1)
        counts = counter.counts()
        assert not task.done()
        release.set()
        await task
        assert counter.counts() == counts
        return counts

    return run(count_open())


def test_a_response_that_does_not_end_is_counted_at_its_start() -> None:
    counts = _count_while_the_request_is_open(
        _http_scope("/stream"), {"type": "http.response.start", "status": 200, "headers": []},
    )
    assert sum(counts.values()) == 1


def test_a_websocket_that_stays_open_is_counted_at_its_accept() -> None:
    counts = _count_while_the_request_is_open(_websocket_scope("/socket"), {"type": "websocket.accept"})
    assert [key.method for key in counts] == ["WS"]


def test_a_request_that_ends_before_it_sends_is_counted_once_at_its_end() -> None:
    counter = RequestOriginCounter()

    async def silent(scope: Message, receive: Any, send: Any) -> None:
        return None

    sent = run(_drive(RequestOriginMiddleware(silent, app_name="main", counter=counter), _http_scope("/x")))
    assert sent == []
    assert sum(counter.counts().values()) == 1


def test_a_request_is_counted_once_however_many_messages_it_sends() -> None:
    counter = RequestOriginCounter()
    app = _build_app(counter)
    sent = run(_drive(app, _http_scope("/api/items/42")))
    assert len(sent) == 2
    assert sum(counter.counts().values()) == 1


def test_lifespan_passes_through_uncounted() -> None:
    counter = RequestOriginCounter()
    seen: list[str] = []

    async def inner(scope: Message, receive: Any, send: Any) -> None:
        seen.append(scope["type"])

    run(_drive(RequestOriginMiddleware(inner, app_name="main", counter=counter), {"type": "lifespan"}))
    assert seen == ["lifespan"]
    assert counter.counts() == {}


# --- pass-through ---------------------------------------------------------------------------------------------------


def test_an_exception_of_the_app_passes_through_and_the_request_is_counted() -> None:
    counter = RequestOriginCounter()

    async def failing(scope: Message, receive: Any, send: Any) -> None:
        raise ValueError("handler failed")

    with pytest.raises(ValueError, match="handler failed"):
        run(_drive(RequestOriginMiddleware(failing, app_name="main", counter=counter), _http_scope("/x")))
    assert sum(counter.counts().values()) == 1


def test_the_messages_sent_are_forwarded_unchanged() -> None:
    counter = RequestOriginCounter()
    messages = [
        {"type": "http.response.start", "status": 201, "headers": [(b"x-one", b"1")]},
        {"type": "http.response.body", "body": b"part", "more_body": True},
        {"type": "http.response.body", "body": b"", "more_body": False},
    ]

    async def app(scope: Message, receive: Any, send: Any) -> None:
        for message in messages:
            await send(message)

    sent = run(_drive(RequestOriginMiddleware(app, app_name="main", counter=counter), _http_scope("/x")))
    assert sent == messages


def test_a_failure_of_the_counting_leaves_one_warning_and_the_requests_go_on(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    counter = RequestOriginCounter()

    def failing_add(origin: RequestOrigin) -> int:
        raise RuntimeError("counting broke")

    monkeypatch.setattr(counter, "add", failing_add)
    app = _build_app(counter)
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    first = run(_drive(app, _http_scope("/api/items/1")))
    second = run(_drive(app, _http_scope("/api/items/2")))
    assert (_status(first), _status(second)) == (200, 200)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert warnings[0].getMessage().startswith("request origin:")


# --- the limit and the log ------------------------------------------------------------------------------------------


def _origin(index: int) -> RequestOrigin:
    return RequestOrigin("main", "GET", f"/t{index}", "(none)", "(none)", "(none)")


def test_tuples_past_the_limit_are_counted_in_the_overflow_tuple() -> None:
    counter = RequestOriginCounter(max_pair_count=2)
    for index in (1, 2, 3, 4):
        counter.add(_origin(index))
    counter.add(_origin(1))
    counts = counter.counts()
    assert counts == {_origin(1): 2, _origin(2): 1, OVERFLOW_ORIGIN: 2}
    assert set(OVERFLOW_ORIGIN) == {"(overflow)"}


def test_the_limit_is_one_thousand_tuples_and_the_next_one_overflows() -> None:
    assert MAX_PAIR_COUNT == 1000
    counter = RequestOriginCounter()
    for index in range(MAX_PAIR_COUNT + 1):
        counter.add(_origin(index))
    counts = counter.counts()
    assert len(counts) == MAX_PAIR_COUNT + 1
    assert counts[OVERFLOW_ORIGIN] == 1


def test_a_line_is_logged_at_the_first_count_and_at_each_power_of_ten(caplog: pytest.LogCaptureFixture) -> None:
    counter = RequestOriginCounter()
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    caplog.clear()
    origin = RequestOrigin("page", "GET", "/{path}", "localhost:8775", "(none)", "same-origin")
    for _ in range(101):
        counter.add(origin)
    lines = [r.getMessage() for r in caplog.records if r.name == LOGGER_NAME]
    assert lines == [
        "request origin: app=page method=GET template=/{path} host=localhost:8775 origin=(none) "
        f"sec_fetch_site=same-origin count={count}"
        for count in (1, 10, 100)
    ]


def test_the_first_overflow_is_logged_with_constant_values(caplog: pytest.LogCaptureFixture) -> None:
    counter = RequestOriginCounter(max_pair_count=1)
    counter.add(_origin(1))
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    caplog.clear()
    counter.add(_origin(2))
    counter.add(_origin(3))
    lines = [r.getMessage() for r in caplog.records if r.name == LOGGER_NAME]
    assert lines == [
        "request origin: app=(overflow) method=(overflow) template=(overflow) host=(overflow) origin=(overflow) "
        "sec_fetch_site=(overflow) count=1",
    ]
