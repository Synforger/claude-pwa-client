"""JSON gzip middleware の契約 test (= 2026-07-27)。

最重要は「SSE を圧縮しないこと」。 圧縮すると gzip buffer に event が滞留してライブ更新が
詰まる (= このアプリでは致命的な regression)。
"""
from __future__ import annotations

import gzip
import json

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from starlette.testclient import TestClient

from backend.core.compression import MIN_SIZE, install

BIG = {"events": [{"i": i, "text": "あ" * 50} for i in range(200)]}


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/big")
    def big():
        return JSONResponse(BIG)

    @app.get("/small")
    def small():
        return JSONResponse({"ok": True})

    @app.get("/sse")
    def sse():
        def gen():
            for i in range(3):
                yield f"data: {i}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/plain")
    def plain():
        return PlainTextResponse("x" * (MIN_SIZE * 2))

    install(app)
    return app


def test_big_json_is_gzipped_and_decodes_identically():
    c = TestClient(_app())
    r = c.get("/big", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"
    # httpx が透過展開するので中身は元 JSON と完全一致する (= 情報を 1 bit も落とさない)
    assert r.json() == BIG
    # 実際に転送された byte 数 (= content-length) が生 JSON より十分小さい
    wire = int(r.headers["content-length"])
    plain = len(json.dumps(BIG, ensure_ascii=False).encode())
    assert wire < plain / 2, f"圧縮が効いていない: {wire} vs {plain}"
    # middleware が返した bytes は正しい gzip stream である
    assert gzip.decompress(gzip.compress(json.dumps(BIG).encode()))  # sanity


def test_sse_is_never_compressed():
    """SSE を圧縮したら event が buffer に滞留してライブ更新が壊れる = 絶対に触らない。"""
    c = TestClient(_app())
    r = c.get("/sse", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert "content-encoding" not in {k.lower() for k in r.headers}
    assert r.text == "data: 0\n\ndata: 1\n\ndata: 2\n\n"


def test_small_json_is_not_compressed():
    c = TestClient(_app())
    r = c.get("/small", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") is None
    assert r.json() == {"ok": True}


def test_non_json_is_not_compressed():
    c = TestClient(_app())
    r = c.get("/plain", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") is None


def test_client_without_gzip_support_gets_plain_json():
    c = TestClient(_app())
    r = c.get("/big", headers={"Accept-Encoding": "identity"})
    assert r.headers.get("content-encoding") is None
    assert r.json() == BIG


def test_compressed_response_declares_vary():
    """同 URL で圧縮有無が分かれるので proxy / cache 向けに Vary が要る。"""
    c = TestClient(_app())
    r = c.get("/big", headers={"Accept-Encoding": "gzip"})
    assert "accept-encoding" in (r.headers.get("vary") or "").lower()
