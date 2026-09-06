"""SPA 配信 mount の契約 test。

最重要は「websocket が静的配信に落ちても例外を立てないこと」。 SPA は "/" に mount して
いるので、 どの WS route にも当たらなかった接続は必ずここへ来る。 StaticFiles は http scope
を前提に assert するため、 素通しすると AssertionError が unhandled 例外として log に立ち、
本物の障害と見分けが付かなくなる (= 実測 13 件、 出所は 2026-07-27 に退役した `/views/ws`
へ繋ぎ続けている古い bundle)。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, WebSocket
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.core.static_files import CacheControlledStaticFiles


@pytest.fixture
def client(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>x</title>", encoding="utf-8")
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "index-abc123.js").write_text("export default 1", encoding="utf-8")

    app = FastAPI()

    @app.websocket("/ws/pty/{session_id}")
    async def pty(ws: WebSocket, session_id: str):
        await ws.accept()
        await ws.send_text(session_id)
        await ws.close()

    app.mount("/", CacheControlledStaticFiles(directory=str(tmp_path), html=True), name="frontend")
    with TestClient(app) as c:
        yield c


def test_unmatched_websocket_is_closed_not_raised(client):
    """退役した WS path への接続は、 例外ではなく close で終わる。

    ここが素通しだと `assert scope["type"] == "http"` が AssertionError になり、
    ASGI の unhandled 例外として error log に traceback が積まれる。
    """
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/views/ws"):
            pass


def test_websocket_route_still_works(client):
    """静的配信より前に居る本物の WS route は素通しされない (= 上の close が広すぎない)。"""
    with client.websocket_connect("/ws/pty/ses_abc") as ws:
        assert ws.receive_text() == "ses_abc"


def test_entrypoints_are_no_cache(client):
    """index.html / manifest.json は毎回鮮度確認させる (= iOS PWA が古い index を掴む対策)。"""
    assert client.get("/index.html").headers["cache-control"] == "no-cache"
    assert client.get("/manifest.json").headers["cache-control"] == "no-cache"
    # SPA の / も index.html なので同じ扱い
    assert client.get("/").headers["cache-control"] == "no-cache"


def test_hashed_assets_are_immutable(client):
    """ファイル名にハッシュが入る assets は永久キャッシュしてよい。"""
    assert client.get("/assets/index-abc123.js").headers["cache-control"] == (
        "public, max-age=31536000, immutable"
    )
