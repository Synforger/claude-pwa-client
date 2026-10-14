"""電話の口: iPhone の app が WebRTC でつなぎ、 声の会話を回す (= 中身は `backend/voice_call/`)。

    POST  /sessions/{sid}/voice/call    接続の申し込み (= SDP の offer → answer)。 つながった時から会話が始まる
    PATCH /sessions/{sid}/voice/call    経路の候補 (= ICE candidate) を足す

本文の形は Pipecat の SmallWebRTC の口と同じ (= iPhone の app は Pipecat の iOS の部品をそのまま使う)。 会話は
画面の会話と同じ持ち主の決まりに従う (= 1 つのタブに 1 つ。 後から開いた方が持つ)。

会話は通話ごとに別の process (= `python -m backend.voice_call.worker`) で動く。 音の送り出しは 10 ms ごとの
受け渡しなので、 backend 本体の他の仕事と同じ流れに載せると途切れる。 この口は process を起こして申し込みを
受け渡すだけで、 process は backend の公開の口を使って会話を回す。

Pipecat は追加で入れる部品。 入っていなければ 501 `voice_call_unavailable`。
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import sys
import uuid
from pathlib import Path

from fastapi import APIRouter, Body, Request

from backend.errors import raise_error
from backend.routes.voice import conversation_settings

logger = logging.getLogger(__name__)

router = APIRouter()

REPO_ROOT = Path(__file__).resolve().parents[2]
# 会話の process が答えを返すまで待つ上限 (= 部品の読み込みは約 0.6 秒。 残りは経路の候補集めで、 普段は数秒)
ANSWER_TIMEOUT_SECS = 30
# 走っている会話の process (= WebRTC の接続の id → process)
_workers: dict[str, asyncio.subprocess.Process] = {}


async def _write(proc: asyncio.subprocess.Process, message: dict) -> None:
    proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
    await proc.stdin.drain()


async def _forget_when_done(pc_id: str, proc: asyncio.subprocess.Process) -> None:
    await proc.wait()
    if _workers.get(pc_id) is proc:
        del _workers[pc_id]
    logger.info("voice call: the call process ended pc_id=%s code=%s", pc_id, proc.returncode)


@router.post("/sessions/{session_id}/voice/call")
async def post_call(request: Request, session_id: str, body: dict = Body(...)) -> dict:
    """接続を申し込む (= SDP の offer を渡し、 answer を受け取る)。

    body: Pipecat の SmallWebRTC の offer (= sdp / type / pc_id / restart_pc)
    """
    # 会話を持てないタブ (= 声を持たない / 聞き取らない) は、 つなぐ前に断る
    settings = conversation_settings(session_id)
    if importlib.util.find_spec("pipecat") is None:
        raise_error(501, "voice_call_unavailable",
                    "この backend には電話の会話の部品が入っていません (= backend/requirements-voice-call.txt)")
    if not isinstance(body.get("sdp"), str) or not isinstance(body.get("type"), str):
        raise_error(400, "voice_bad_request", "本文は SDP の offer (= sdp と type) で渡します")

    host, port = request.scope.get("server") or ("127.0.0.1", 8765)
    start = {
        "type": "start", "base_url": f"http://{host}:{port}", "session_id": session_id,
        "client": f"call-{uuid.uuid4().hex[:12]}", "marks": list(settings["marks"]),
        "conversation": settings["conversation"], "turn": settings["listen"]["turn"],
    }
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "backend.voice_call.worker", cwd=str(REPO_ROOT),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
    offer = {k: v for k, v in body.items() if k != "type"}
    await _write(proc, start)
    await _write(proc, {"type": "offer", "type_": body["type"], **offer})
    try:
        line = await asyncio.wait_for(proc.stdout.readline(), ANSWER_TIMEOUT_SECS)
        reply = json.loads(line) if line else {"type": "error", "message": "the call process ended"}
    except (asyncio.TimeoutError, ValueError) as error:
        reply = {"type": "error", "message": f"no answer from the call process: {error!r}"}
    if reply.get("type") != "answer":
        if proc.returncode is None:
            proc.kill()
        logger.warning("voice call: could not connect session=%s: %s", session_id, reply.get("message"))
        raise_error(502, "voice_call_failed", "電話の会話をつなげませんでした", reason=reply.get("message", ""))
    answer = reply["answer"]
    _workers[answer["pc_id"]] = proc
    asyncio.create_task(_forget_when_done(answer["pc_id"], proc))
    logger.info("voice call: connecting session=%s pc_id=%s", session_id, answer["pc_id"])
    return answer


@router.patch("/sessions/{session_id}/voice/call")
async def patch_call(session_id: str, body: dict = Body(...)) -> dict:
    """経路の候補を足す。

    body: Pipecat の SmallWebRTC の patch (= pc_id / candidates)
    """
    proc = _workers.get(body.get("pc_id") or "")
    if proc is None or proc.returncode is not None:
        raise_error(404, "voice_call_unknown", "この接続は見つかりません")
    if not isinstance(body.get("candidates"), list):
        raise_error(400, "voice_bad_request", "本文は pc_id と candidates で渡します")
    await _write(proc, {"type": "patch", "pc_id": body["pc_id"], "candidates": body["candidates"]})
    return {"status": "success"}
