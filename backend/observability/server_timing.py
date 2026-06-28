"""ADR-012 Server-Timing: response header で phase 別 timing を露出する ASGI middleware。

W3C Server-Timing spec: https://www.w3.org/TR/server-timing/
形式: `Server-Timing: phase;dur=12.3, phase2;dur=4.5`

phase の積み立ては `with timing_phase("db"):` で行い、 ContextVar 経由で middleware が response
header に inject する。 W1 で書いた純 ASGI middleware の流儀 (= BaseHTTPMiddleware を避ける)
で contextvars 伝播を保つ。
"""
from __future__ import annotations

import time
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

_timings_var: ContextVar[OrderedDict[str, float]] = ContextVar("server_timings", default=OrderedDict())


def _current() -> OrderedDict[str, float]:
    """現 context の timing dict を返す (= 未設定なら空 OrderedDict)。

    contextvars の default は同じ instance を返すので mutate すると漏れる。 必ず set() してから
    使う想定だが、 念のため空 OrderedDict() を返して mutate を吸収する設計。
    """
    return _timings_var.get()


def add(name: str, duration_ms: float) -> None:
    """1 phase の duration を context の dict に積み足す (= 同名は加算)。"""
    t = _current()
    t[name] = t.get(name, 0.0) + duration_ms


@contextmanager
def timing_phase(name: str):
    """`with timing_phase("db"):` で囲った区間の elapsed を add(name, ms) する。"""
    started = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        add(name, elapsed_ms)


def render(timings: OrderedDict[str, float]) -> str:
    """OrderedDict → Server-Timing header 値文字列。"""
    parts = []
    for name, dur in timings.items():
        # name は token 制約あり、 簡易 sanitize: 英数字 + _ - 以外を _ に
        safe = "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in name)
        parts.append(f"{safe};dur={dur:.2f}")
    return ", ".join(parts)


class ServerTimingMiddleware:
    """ASGI middleware: request 全体の elapsed と context に積まれた phase timings を
    response header `Server-Timing` に inject する。
    """

    TOTAL_KEY = "total"

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        timings: OrderedDict[str, float] = OrderedDict()
        token = _timings_var.set(timings)
        start = time.perf_counter()

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                timings[self.TOTAL_KEY] = (time.perf_counter() - start) * 1000.0
                header_value = render(timings).encode("ascii")
                headers = list(message.get("headers") or [])
                replaced = False
                for i, (n, v) in enumerate(headers):
                    if n.lower() == b"server-timing":
                        # 既存があれば追記 (= ", " で連結) して尊重
                        if v:
                            headers[i] = (n, v + b", " + header_value)
                        else:
                            headers[i] = (n, header_value)
                        replaced = True
                        break
                if not replaced:
                    headers.append((b"server-timing", header_value))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            _timings_var.reset(token)


def install(app) -> None:
    """FastAPI app に ServerTimingMiddleware を登録する糖衣 (= main.py から呼ぶ)。"""
    app.add_middleware(ServerTimingMiddleware)


__all__ = ["timing_phase", "add", "render", "ServerTimingMiddleware", "install"]
