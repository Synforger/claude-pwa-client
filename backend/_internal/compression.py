"""JSON response だけを gzip する純 ASGI middleware (= 2026-07-27 体感速度改善)。

## なぜ必要か

PWA は携帯から Tailscale 経由で繋ぐ。 タブを開くたびに走る `GET /jsonl/history/{sid}` は
直近 N 行を丸ごと返す設計 (= client=射影) で、 実測 **1.18MB** あった (= tool 入出力を
含む event 列)。 これは LAN の実測では 80ms でも、 携帯の実効帯域では体感遅延の主因になる。
JSON は key が反復するので gzip が非常によく効く (= 実測 1.18MB → 約 1/10)。 **中身は
1 byte も変えず**転送量だけ落とすので、 表示ロジックへの影響がゼロなのが利点。

## なぜ Starlette の GZipMiddleware を使わないか

本 backend の主役は SSE (= `/stream/unified` 等の text/event-stream)。 GZipMiddleware は
content-type を見ずに streaming response も圧縮対象にするため、 gzip の内部 buffer に
event が滞留して**ライブ更新が遅延 / 詰まる**危険がある (= このアプリでは致命)。

そこで本 middleware は「完結した JSON response」 だけを対象にする:
  - content-type が application/json のものだけ (= SSE の text/event-stream は素通し)
  - 既に content-encoding が付いてるものは触らない
  - MIN_SIZE 未満は圧縮しない (= 小さい応答は gzip header 分で逆に太る)
  - body が複数 chunk に分かれて届く streaming JSON も、 more_body を辿って全部
    集めてから 1 回で圧縮する (= 途中 flush しないので SSE と違い滞留の概念がない)

BaseHTTPMiddleware でなく純 ASGI なのは既存 (correlation / server_timing) と同じ流儀で、
contextvars 伝播を壊さないため。
"""
from __future__ import annotations

import gzip
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# これ未満は圧縮しない。 gzip header/trailer は約 20 byte あり、 小さい body では
# 却って大きくなる + CPU の無駄。 1KB は一般的な閾値 (= Starlette の既定と同値)。
MIN_SIZE = 1024

# 圧縮レベル。 6 = zlib 既定 (速度と圧縮率の均衡)。 9 にしても JSON では数 % しか
# 縮まない一方 CPU は跳ねるので、 発熱を嫌う本アプリでは 6 のまま使う。
COMPRESS_LEVEL = 6

_TARGET_TYPE = b"application/json"


def _accepts_gzip(scope: Scope) -> bool:
    for name, value in scope.get("headers") or []:
        if name == b"accept-encoding":
            return b"gzip" in value.lower()
    return False


def _header(headers: list[tuple[bytes, bytes]], key: bytes) -> bytes | None:
    for name, value in headers:
        if name.lower() == key:
            return value
    return None


class JsonGzipMiddleware:
    """完結した application/json response のみ gzip する。 SSE は素通し。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _accepts_gzip(scope):
            await self.app(scope, receive, send)
            return

        start_message: Message | None = None
        chunks: list[bytes] = []
        passthrough = False

        async def send_wrapper(message: Message) -> None:
            nonlocal start_message, passthrough

            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                ctype = _header(headers, b"content-type") or b""
                already = _header(headers, b"content-encoding")
                # JSON 以外 (= SSE / HTML / 画像) と圧縮済みは一切触らない
                if not ctype.lower().startswith(_TARGET_TYPE) or already:
                    passthrough = True
                    await send(message)
                    return
                # 圧縮するかは body 全量を見てから決めるので、 start はここで保留する
                start_message = message
                return

            if message["type"] == "http.response.body":
                if passthrough:
                    await send(message)
                    return
                chunks.append(message.get("body") or b"")
                if message.get("more_body"):
                    return
                # body 完結。 ここで初めて圧縮可否を決めて start → body を送る
                body = b"".join(chunks)
                assert start_message is not None
                headers = [
                    (n, v) for n, v in (start_message.get("headers") or [])
                    if n.lower() != b"content-length"
                ]
                if len(body) >= MIN_SIZE:
                    body = gzip.compress(body, COMPRESS_LEVEL)
                    headers.append((b"content-encoding", b"gzip"))
                    # 同 URL で圧縮有無が分かれるので proxy / cache 向けに Vary を明示
                    vary = _header(headers, b"vary")
                    if vary is None:
                        headers.append((b"vary", b"Accept-Encoding"))
                    elif b"accept-encoding" not in vary.lower():
                        headers = [
                            (n, (v + b", Accept-Encoding") if n.lower() == b"vary" else v)
                            for n, v in headers
                        ]
                headers.append((b"content-length", str(len(body)).encode("ascii")))
                start_message["headers"] = headers
                await send(start_message)
                await send({"type": "http.response.body", "body": body, "more_body": False})
                return

            await send(message)

        await self.app(scope, receive, send_wrapper)


def install(app: Any) -> None:
    """FastAPI app に JSON gzip middleware を差す (= main.py から呼ぶ)。"""
    app.add_middleware(JsonGzipMiddleware)
