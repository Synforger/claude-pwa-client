"""correlation id (= W3C traceparent 互換) の発行 + ContextVar 伝播 + FastAPI middleware。

ADR-012 採用 (= W3C Trace Context format + structlog ContextVar 連携):
    - trace_id = 32 hex (= 16 bytes 乱数 hex)
    - span_id  = 16 hex (= 8 bytes 乱数 hex)
    - flags    = 01 (= sampled)
    - corr_id  = trace_id 頭 8 文字 (= 既存 X-Correlation-Id 互換、 frontend / log で短縮表示)

伝播経路:
    1. HTTP request 受信 → CorrelationMiddleware が `traceparent` header を読む or 新規生成
    2. trace_ctx_var に dict を set (= asyncio task copy_context で全 layer 串刺し)
    3. SSE / WS pump で current_corr_id() を event envelope に注入 (= W1 routes.py の _inject_envelope)
    4. structlog processor が trace.id / span.id を log entry に merge
    5. response header に `traceparent` を echo (= 上流 trace との結合用)

将来の expansion:
    - WebSocket 接続にも middleware 相当の wrapper (= /ws/* で対応 header / sub-protocol)
    - OTLP exporter (= Honeycomb / Tempo / Jaeger) に流す時は本 ContextVar をそのまま OTel に渡す
"""
from __future__ import annotations

import secrets
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

# 全 layer 串刺し用 ContextVar。 dict 形式で持ち、 trace_id / span_id / flags を保持。
_trace_ctx_var: ContextVar[dict[str, str]] = ContextVar("trace_ctx", default={})

# 旧 stub の 8hex 専用 ContextVar (= W1 で書いた API) との後方互換。 新コードは _trace_ctx_var 経由で。
_legacy_current: ContextVar[str | None] = ContextVar("corr_id", default=None)


def new_corr_id() -> str:
    """W3C trace-id 互換の 8 hex 文字列 (= 4 bytes 乱数の hex 表現)。

    1 接続 / 1 turn 等の論理単位ごとに 1 つ発行して全 layer に伝播する想定。 W3C trace_id の頭 8 文字
    と一致する形なので将来 OTLP backend に流す時に互換性が保てる。
    """
    return secrets.token_hex(4)


def new_traceparent() -> str:
    """W3C Trace Context format の traceparent 文字列を新規生成。

    format: `00-<32 hex trace_id>-<16 hex span_id>-01`
    """
    trace_id = secrets.token_hex(16)
    span_id = secrets.token_hex(8)
    return f"00-{trace_id}-{span_id}-01"


def parse_traceparent(value: str | None) -> dict[str, str] | None:
    """`traceparent` header を解釈し、 {version, trace_id, span_id, flags} dict を返す。

    不正な format (= 区切り数 / hex 長さ / version) は None を返し、 呼出側で new_traceparent() に
    fallback する想定 (= 上流が壊れた header を送ってきても落とさない、 W3C 推奨)。
    """
    if not value or not isinstance(value, str):
        return None
    parts = value.strip().split("-")
    if len(parts) != 4:
        return None
    version, trace_id, span_id, flags = parts
    if version != "00":
        return None
    if len(trace_id) != 32 or len(span_id) != 16 or len(flags) != 2:
        return None
    for chunk in (trace_id, span_id, flags):
        try:
            int(chunk, 16)
        except ValueError:
            return None
    # all-zero trace_id / span_id は W3C 仕様で invalid
    if int(trace_id, 16) == 0 or int(span_id, 16) == 0:
        return None
    return {"version": version, "trace_id": trace_id, "span_id": span_id, "flags": flags}


def build_traceparent(ctx: dict[str, str]) -> str:
    """ctx dict から traceparent 文字列を組み立て (= response header / 下流伝搬用)。"""
    return f"00-{ctx['trace_id']}-{ctx['span_id']}-{ctx.get('flags', '01')}"


def current_trace_context() -> dict[str, str]:
    """現 context の trace dict を返す (= 未設定なら空 dict)。

    structlog processor / SSE envelope / WS frame の trace 結合に使う。
    """
    return _trace_ctx_var.get()


def current_corr_id() -> str:
    """現 context の corr_id (= trace_id 頭 8 hex) を返す。

    未設定なら新規発行 + ContextVar に set (= W1 stub の互換動作、 既存 routes.py の
    `_inject_envelope(event, sid)` で SSE event payload に必ず付ける契約を維持)。
    """
    ctx = _trace_ctx_var.get()
    if ctx and ctx.get("trace_id"):
        return ctx["trace_id"][:8]
    legacy = _legacy_current.get()
    if legacy is not None:
        return legacy
    fresh = new_corr_id()
    _legacy_current.set(fresh)
    return fresh


def bind_corr_id(corr_id: str) -> None:
    """legacy stub API。 新コードは bind_trace_context() を使う、 ただし W1 で書いた呼出を壊さないため残す。"""
    _legacy_current.set(corr_id)


def bind_trace_context(ctx: dict[str, str]) -> None:
    """trace 全 dict を明示 set。 middleware / test fixture から使う。"""
    _trace_ctx_var.set(ctx)


@contextmanager
def corr_id_scope(corr_id: str | None = None):
    """限定スコープで legacy corr_id を貼り、 抜けると元に戻す (= W1 stub の後方互換)。"""
    token = _legacy_current.set(corr_id or new_corr_id())
    try:
        yield _legacy_current.get()
    finally:
        _legacy_current.reset(token)


@contextmanager
def trace_context_scope(ctx: dict[str, str] | None = None):
    """限定スコープで trace 全 dict を貼り、 抜けると元に戻す。

    test fixture / 同期処理境界で「この block 全部を 1 trace で記録」 したい時に。
    None を渡すと新規 traceparent を発行。
    """
    if ctx is None:
        parsed = parse_traceparent(new_traceparent())
        assert parsed is not None
        ctx = parsed
    token = _trace_ctx_var.set(ctx)
    try:
        yield _trace_ctx_var.get()
    finally:
        _trace_ctx_var.reset(token)


class CorrelationMiddleware:
    """ASGI middleware: 受信 request の `traceparent` header を読んで trace_ctx_var に set、
    response 送出時に `traceparent` を echo する。

    starlette / FastAPI の BaseHTTPMiddleware は SSE / StreamingResponse で contextvars
    伝播が壊れる既知問題があるため、 純 ASGI middleware として実装 (= contextvars 自然継承)。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        upstream_header: str | None = None
        for name, value in scope.get("headers") or []:
            if name == b"traceparent":
                try:
                    upstream_header = value.decode("ascii")
                except UnicodeDecodeError:
                    upstream_header = None
                break

        ctx = parse_traceparent(upstream_header)
        if ctx is None:
            ctx = parse_traceparent(new_traceparent())
            assert ctx is not None

        token = _trace_ctx_var.set(ctx)
        traceparent_out = build_traceparent(ctx).encode("ascii")

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                replaced = False
                for i, (n, _) in enumerate(headers):
                    if n == b"traceparent":
                        headers[i] = (b"traceparent", traceparent_out)
                        replaced = True
                        break
                if not replaced:
                    headers.append((b"traceparent", traceparent_out))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            _trace_ctx_var.reset(token)


def install(app) -> None:
    """FastAPI app に CorrelationMiddleware を登録する糖衣 (= main.py から呼ぶ)。"""
    app.add_middleware(CorrelationMiddleware)


__all__ = [
    "new_corr_id",
    "new_traceparent",
    "parse_traceparent",
    "build_traceparent",
    "current_trace_context",
    "current_corr_id",
    "bind_corr_id",
    "bind_trace_context",
    "corr_id_scope",
    "trace_context_scope",
    "CorrelationMiddleware",
    "install",
]
