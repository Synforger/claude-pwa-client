"""ADR-012: W3C traceparent 互換 corr_id + CorrelationMiddleware の動作検証。

scope:
    - new_traceparent / parse_traceparent の round-trip と invalid 入力の reject
    - current_corr_id / current_trace_context が ContextVar から正しく取れる
    - trace_context_scope の出入りで context が漏れない
    - CorrelationMiddleware が ASGI レイヤで:
        - 上流 `traceparent` header を honor して echo
        - garbage / 無効入力時に新規生成
        - 全 endpoint で response header に `traceparent` を必ず付与
        - request handler 内で current_corr_id() が同じ trace_id 頭 8 文字を返す
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.observability.correlation import (
    CorrelationMiddleware,
    bind_trace_context,
    build_traceparent,
    current_corr_id,
    current_trace_context,
    new_corr_id,
    new_traceparent,
    parse_traceparent,
    trace_context_scope,
)


def _run_async(coro):
    """asyncio.run は MainThread の event loop policy を None に上書きする副作用があり、
    後続 test (= test_fork 等で get_event_loop() 経路) を壊す。 自前で loop を作って閉じ、
    後始末で MainThread の policy も新規 loop に差し戻すヘルパー。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        # MainThread の event loop policy を維持して get_event_loop() を再び正常化する
        asyncio.set_event_loop(asyncio.new_event_loop())


# --- 純粋関数 -------------------------------------------------------------


def test_new_corr_id_is_8_hex():
    cid = new_corr_id()
    assert len(cid) == 8
    int(cid, 16)  # raises if not hex


def test_new_traceparent_format():
    tp = new_traceparent()
    parts = tp.split("-")
    assert len(parts) == 4
    assert parts[0] == "00"
    assert len(parts[1]) == 32 and len(parts[2]) == 16 and len(parts[3]) == 2


def test_parse_traceparent_roundtrip():
    tp = new_traceparent()
    ctx = parse_traceparent(tp)
    assert ctx is not None
    assert build_traceparent(ctx) == tp


@pytest.mark.parametrize("bad", [
    None,
    "",
    "garbage",
    "00-tooshort-tooshort-01",
    "01-" + "a" * 32 + "-" + "b" * 16 + "-01",     # version != 00
    "00-" + "g" * 32 + "-" + "b" * 16 + "-01",     # non-hex
    "00-" + "0" * 32 + "-" + "b" * 16 + "-01",     # all-zero trace_id (W3C invalid)
    "00-" + "a" * 32 + "-" + "0" * 16 + "-01",     # all-zero span_id (W3C invalid)
    "00-" + "a" * 30 + "-" + "b" * 16 + "-01",     # short trace_id
])
def test_parse_traceparent_rejects_invalid(bad):
    assert parse_traceparent(bad) is None


def test_current_corr_id_fresh_default():
    """ContextVar 未設定状態でも例外なく 8 hex を返す (= W1 stub 互換)。"""
    cid = current_corr_id()
    assert len(cid) == 8
    int(cid, 16)


def test_trace_context_scope_sets_and_unsets():
    outside_ctx = current_trace_context()
    outside_corr = current_corr_id()

    ctx = parse_traceparent(new_traceparent())
    assert ctx is not None
    with trace_context_scope(ctx):
        inside_ctx = current_trace_context()
        assert inside_ctx == ctx
        assert current_corr_id() == ctx["trace_id"][:8]

    # scope を抜けると外側に戻る
    assert current_trace_context() == outside_ctx
    # 外側 corr_id は legacy stub 経路で再計算、 unchanged 保証は scope 内 trace_id とは別
    assert isinstance(outside_corr, str) and len(outside_corr) == 8


def test_bind_trace_context_persists_in_task():
    ctx = parse_traceparent(new_traceparent())
    assert ctx is not None

    async def runner():
        bind_trace_context(ctx)
        # 同じ task 内で値が読める
        assert current_trace_context() == ctx
        assert current_corr_id() == ctx["trace_id"][:8]

    _run_async(runner())


# --- ASGI middleware -----------------------------------------------------


class _RecordingApp:
    """ASGI app stub。 受信した request の handler 内で current_corr_id() / current_trace_context()
    を記録し、 plain "ok" response を返す。 middleware が ContextVar を正しく set してることを
    request scope レベルで確認する用。
    """

    def __init__(self) -> None:
        self.observed_corr_id: str | None = None
        self.observed_ctx: dict[str, str] | None = None

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        assert scope["type"] == "http"
        # handler 内 (= middleware が ContextVar set 済の段階)
        self.observed_corr_id = current_corr_id()
        self.observed_ctx = current_trace_context()
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/plain")],
        })
        await send({"type": "http.response.body", "body": b"ok"})


async def _drive(middleware: CorrelationMiddleware, headers: list[tuple[bytes, bytes]]) -> dict[str, str]:
    """ASGI middleware を request 1 本に対して走らせ、 response header を dict で返す。"""
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/probe",
        "headers": headers,
    }
    await middleware(scope, receive, send)
    # response.start を探して headers を回収
    for m in sent:
        if m["type"] == "http.response.start":
            return {k.decode("ascii"): v.decode("ascii") for k, v in m["headers"]}
    raise AssertionError("no http.response.start received")


def test_middleware_generates_traceparent_when_absent():
    app = _RecordingApp()
    mw = CorrelationMiddleware(app)
    headers = _run_async(_drive(mw, []))
    assert "traceparent" in headers
    ctx = parse_traceparent(headers["traceparent"])
    assert ctx is not None
    # request handler が見た corr_id が echo した traceparent と一致
    assert app.observed_corr_id == ctx["trace_id"][:8]
    assert app.observed_ctx == ctx


def test_middleware_honors_upstream_traceparent():
    upstream = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
    app = _RecordingApp()
    mw = CorrelationMiddleware(app)
    headers = _run_async(_drive(mw, [(b"traceparent", upstream.encode("ascii"))]))
    assert headers["traceparent"] == upstream
    assert app.observed_corr_id == "a" * 8


def test_middleware_replaces_garbage_upstream():
    app = _RecordingApp()
    mw = CorrelationMiddleware(app)
    headers = _run_async(_drive(mw, [(b"traceparent", b"garbage")]))
    assert headers["traceparent"] != "garbage"
    assert parse_traceparent(headers["traceparent"]) is not None


def test_middleware_replaces_existing_response_traceparent():
    """もし下流 handler が response に traceparent を付けていた場合、 middleware の値で上書きする
    (= 上書きしないと echo の意味が薄れる、 middleware 一括管理が崩れる)。"""

    class _AppEmitsTraceparent:
        async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"traceparent", b"00-deadbeef-cafe-01")],  # 不正だが上書き検査用
            })
            await send({"type": "http.response.body", "body": b""})

    mw = CorrelationMiddleware(_AppEmitsTraceparent())
    upstream = "00-" + "f" * 32 + "-" + "e" * 16 + "-01"
    headers = _run_async(_drive(mw, [(b"traceparent", upstream.encode("ascii"))]))
    assert headers["traceparent"] == upstream


def test_middleware_does_not_leak_context_after_request():
    """request 完了後は ContextVar が rollback される (= 次 request に漏れない)。"""
    mw = CorrelationMiddleware(_RecordingApp())
    upstream = "00-" + "1" * 32 + "-" + "2" * 16 + "-01"
    _run_async(_drive(mw, [(b"traceparent", upstream.encode("ascii"))]))
    # middleware の外では legacy fresh が返る (= upstream の trace_id ではない)
    after = current_trace_context()
    assert after.get("trace_id") != "1" * 32


def test_middleware_passes_through_non_http_scope():
    """websocket / lifespan scope は middleware が触らず素通しする (= http 以外で破壊しない)。"""
    called = {"n": 0}

    class _Plain:
        async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
            called["n"] += 1
            assert scope["type"] == "websocket"

    mw = CorrelationMiddleware(_Plain())

    async def receive() -> dict[str, Any]:
        return {"type": "websocket.disconnect"}

    async def send(_msg: dict[str, Any]) -> None:
        pass

    _run_async(mw({"type": "websocket"}, receive, send))
    assert called["n"] == 1
