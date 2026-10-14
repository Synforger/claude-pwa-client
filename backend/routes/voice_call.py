"""電話の口: iPhone の app が WebRTC でつなぎ、 声の会話を backend の中で回す (= 中身は `backend/voice_call/`)。

    POST  /sessions/{sid}/voice/call    接続の申し込み (= SDP の offer → answer)。 つながった時から会話が始まる
    PATCH /sessions/{sid}/voice/call    経路の候補 (= ICE candidate) を足す

本文の形は Pipecat の SmallWebRTC の口と同じ (= iPhone の app は Pipecat の iOS の部品をそのまま使う)。 会話は
画面の会話と同じ持ち主の決まりに従う (= 1 つのタブに 1 つ。 後から開いた方が持つ)。

Pipecat は追加で入れる部品。 入っていなければ 501 `voice_call_unavailable`。
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Body

from backend.errors import raise_error
from backend.routes.voice import conversation_settings
from backend.terminal.routes import pty_send

logger = logging.getLogger(__name__)

router = APIRouter()

# 受け口 (= 接続ごとの WebRTC の相手を覚える)。 Pipecat を読むのは、 初めて電話が来た時。
_handler = None
# 走っている会話 (= 途中で回収されないように持つ)
_calls: set[asyncio.Task] = set()


def _pipecat():
    try:
        from pipecat.transports.smallwebrtc.request_handler import (
            IceCandidate,
            SmallWebRTCPatchRequest,
            SmallWebRTCRequest,
            SmallWebRTCRequestHandler,
        )

        from backend.voice_call.pipeline import run_call
    except ImportError:
        raise_error(501, "voice_call_unavailable",
                    "この backend には電話の会話の部品が入っていません (= backend/requirements-voice-call.txt)")

    def patch_of(body: dict):
        return SmallWebRTCPatchRequest(
            pc_id=body["pc_id"], candidates=[IceCandidate(**c) for c in body.get("candidates") or []])

    return SmallWebRTCRequest, patch_of, SmallWebRTCRequestHandler, run_call


async def _send(session_id: str, text: str) -> bool:
    """そのタブへ 1 通送る (= 画面で打った時と同じ口)。"""
    result = await pty_send(session_id, {"text": text, "enter": True}, None)
    return bool(result.get("ok"))


@router.post("/sessions/{session_id}/voice/call")
async def post_call(session_id: str, body: dict = Body(...)) -> dict:
    """接続を申し込む (= SDP の offer を渡し、 answer を受け取る)。

    body: Pipecat の SmallWebRTC の offer (= sdp / type / pc_id / restart_pc)
    """
    global _handler
    # 会話を持てないタブ (= 声を持たない / 聞き取らない) は、 つなぐ前に断る
    conversation_settings(session_id)
    request_cls, _, handler_cls, run_call = _pipecat()
    client = f"call-{uuid.uuid4().hex[:12]}"
    if _handler is None:
        _handler = handler_cls()

    async def connected(connection) -> None:
        task = asyncio.create_task(run_call(session_id, connection, client, _send))
        _calls.add(task)
        task.add_done_callback(_calls.discard)

    try:
        request = request_cls.from_dict(body)
    except (KeyError, TypeError, ValueError):
        raise_error(400, "voice_bad_request", "本文は SDP の offer (= sdp と type) で渡します")
    return await _handler.handle_web_request(request=request, webrtc_connection_callback=connected)


@router.patch("/sessions/{session_id}/voice/call")
async def patch_call(session_id: str, body: dict = Body(...)) -> dict:
    """経路の候補を足す。

    body: Pipecat の SmallWebRTC の patch (= pc_id / candidates)
    """
    if _handler is None:
        raise_error(404, "voice_call_unknown", "この接続は見つかりません")
    _, patch_of, _, _ = _pipecat()
    try:
        request = patch_of(body)
    except (KeyError, TypeError, ValueError):
        raise_error(400, "voice_bad_request", "本文は pc_id と candidates で渡します")
    await _handler.handle_patch_request(request)
    return {"status": "success"}
