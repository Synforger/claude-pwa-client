"""ADR-012 Server-Timing: phase 積み立て + response header inject の動作検証。"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Any

import pytest

from backend.observability.server_timing import (
    ServerTimingMiddleware,
    add,
    render,
    timing_phase,
    _timings_var,
)


def test_render_simple():
    od = OrderedDict([("db", 12.345), ("ren", 4.0)])
    assert render(od) == "db;dur=12.35, ren;dur=4.00"


def test_render_sanitizes_name():
    od = OrderedDict([("space here", 1.0), ("dot.name", 2.0)])
    out = render(od)
    assert "space_here;dur=1.00" in out
    assert "dot_name;dur=2.00" in out


def test_render_empty_returns_empty_string():
    assert render(OrderedDict()) == ""


def test_timing_phase_adds_duration():
    # ContextVar を test 限定 OrderedDict に set してから測る
    token = _timings_var.set(OrderedDict())
    try:
        with timing_phase("step"):
            pass
        timings = _timings_var.get()
        assert "step" in timings
        assert timings["step"] >= 0
    finally:
        _timings_var.reset(token)


def test_timing_phase_accumulates_same_name():
    token = _timings_var.set(OrderedDict())
    try:
        add("step", 1.5)
        add("step", 2.5)
        timings = _timings_var.get()
        assert timings["step"] == 4.0
    finally:
        _timings_var.reset(token)


# --- ASGI middleware -----------------------------------------------------


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


class _App:
    """Server-Timing middleware の test 用 ASGI app: timing_phase で phase 追加して 200 返す。"""

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        assert scope["type"] == "http"
        with timing_phase("handler"):
            pass
        add("manual", 7.5)
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/plain")],
        })
        await send({"type": "http.response.body", "body": b"ok"})


async def _drive(mw: ServerTimingMiddleware) -> dict[str, str]:
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await mw({"type": "http", "method": "GET", "path": "/", "headers": []}, receive, send)
    for m in sent:
        if m["type"] == "http.response.start":
            return {k.decode("ascii").lower(): v.decode("ascii") for k, v in m["headers"]}
    raise AssertionError("no response.start")


def test_middleware_adds_server_timing_header():
    mw = ServerTimingMiddleware(_App())
    headers = _run_async(_drive(mw))
    val = headers.get("server-timing", "")
    assert "handler;dur=" in val
    assert "manual;dur=7.50" in val
    assert "total;dur=" in val


def test_middleware_passes_through_non_http_scope():
    called = {"n": 0}

    class _Plain:
        async def __call__(self, scope, receive, send):
            called["n"] += 1

    mw = ServerTimingMiddleware(_Plain())

    async def receive():
        return {"type": "websocket.disconnect"}

    async def send(_m):
        pass

    _run_async(mw({"type": "websocket"}, receive, send))
    assert called["n"] == 1


def test_middleware_resets_context_after_request():
    mw = ServerTimingMiddleware(_App())
    _run_async(_drive(mw))
    # request 後 context は default (= 空 dict-like) に戻る
    cur = _timings_var.get()
    assert "handler" not in cur
    assert "manual" not in cur
