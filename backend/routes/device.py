"""iPhone の app を、 この Mac の agent の手にする口 (= 中身は `backend/device/hub.py`)。

    WS   /device/ws        app がつなぐ (= 起きている間。 最初に hello で操作の一覧を送る)
    POST /device/ops       この Mac の命令 (= `cpc device`) が操作を 1 つ頼む
    GET  /device/catalog   つながっているかと、 できる操作の一覧
    POST /device/screen    app の画面の配信が 1 枚送る (= JPEG。 最後の 1 枚だけを持つ)
    POST /device/screen/state  画面の配信の始まりと終わり
    GET  /device/screen    最後の 1 枚の在処と、 配信しているか (= `cpc device screen`)

頼む口と一覧の口と画面を見る口は、 この Mac の中からだけ受ける (= `/debug` と同じ見分け方。 Tailscale を通った頼みは
宛名が tailnet の名前になる)。
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Body, HTTPException, Request, WebSocket, WebSocketDisconnect

from backend.device.hub import DeviceFailed, DeviceHub, DeviceOffline, DeviceTimeout, UnknownOp
from backend.device.screen import NotJpeg, ScreenStore
from backend.paths import DATA_DIR
from backend.routes.debug import _ensure_localhost

logger = logging.getLogger(__name__)
router = APIRouter()

# app が最初の hello を送るまで待つ長さ
HELLO_TIMEOUT_S = 10.0

hub = DeviceHub(catalog_path=DATA_DIR / "device_catalog.json", files_dir=DATA_DIR / "device-files")
screen = ScreenStore(files_dir=DATA_DIR / "device-files")


@router.websocket("/device/ws")
async def device_socket(ws: WebSocket) -> None:
    await ws.accept()
    try:
        hello = json.loads(await asyncio.wait_for(ws.receive_text(), HELLO_TIMEOUT_S))
    except (asyncio.TimeoutError, ValueError, WebSocketDisconnect):
        await ws.close(code=4000, reason="hello expected")
        return
    if not isinstance(hello, dict) or hello.get("type") != "hello":
        await ws.close(code=4000, reason="hello expected")
        return
    lock = asyncio.Lock()

    async def send(message: dict) -> None:
        async with lock:
            await ws.send_text(json.dumps(message, ensure_ascii=False))

    link = hub.attach(send, hello)
    try:
        while True:
            try:
                message = json.loads(await ws.receive_text())
            except ValueError:
                continue
            if isinstance(message, dict):
                hub.receive(message)
    except WebSocketDisconnect:
        pass
    finally:
        hub.detach(link)


@router.post("/device/ops")
async def post_device_op(request: Request, body: dict = Body(...)) -> dict:
    _ensure_localhost(request)
    op = body.get("op")
    args = body.get("args") or {}
    timeout = body.get("timeout_s")
    if not isinstance(op, str) or not op or not isinstance(args, dict):
        raise HTTPException(status_code=400, detail="op (string) and args (object) are required")
    if timeout is not None and (not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0):
        raise HTTPException(status_code=400, detail="timeout_s must be a positive number")
    try:
        result = await hub.call(op, args, timeout)
    except DeviceOffline as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except UnknownOp as error:
        names = sorted(o.get("name") for o in hub.status().get("catalog") or [])
        raise HTTPException(status_code=404, detail={"unknown": str(error), "known": names}) from error
    except DeviceTimeout as error:
        raise HTTPException(status_code=504, detail=str(error)) from error
    except DeviceFailed as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"ok": True, "result": result}


@router.get("/device/catalog")
async def get_device_catalog(request: Request) -> dict:
    _ensure_localhost(request)
    return hub.status()


@router.post("/device/screen")
async def post_device_screen(request: Request) -> dict:
    try:
        return screen.receive(await request.body())
    except NotJpeg as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/device/screen/state")
async def post_device_screen_state(body: dict = Body(...)) -> dict:
    live = body.get("live")
    if not isinstance(live, bool):
        raise HTTPException(status_code=400, detail="live (bool) is required")
    screen.set_live(live)
    return {"live": live}


@router.get("/device/screen")
async def get_device_screen(request: Request) -> dict:
    _ensure_localhost(request)
    return screen.status()
