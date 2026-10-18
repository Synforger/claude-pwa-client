"""電話の口: iPhone の app が WebRTC でつなぎ、 声の会話を回す (= 中身は `backend/voice_call/`)。

    POST  /sessions/{sid}/voice/call    接続の申し込み (= SDP の offer → answer)。 つながった時から会話が始まる
    PATCH /sessions/{sid}/voice/call    経路の候補 (= ICE candidate) を足す
    POST  /sessions/{sid}/voice/call/volume   通話中の声の大きさの倍率を変える (= 端末の画面のつまみ)

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
from backend.state import calls_by_conn

logger = logging.getLogger(__name__)

router = APIRouter()

REPO_ROOT = Path(__file__).resolve().parents[2]
# 会話の process が答えを返すまで待つ上限 (= 部品の読み込みは約 0.6 秒。 残りは経路の候補集めで、 普段は数秒)
ANSWER_TIMEOUT_SECS = 30
# 走っている会話の process (= WebRTC の接続の id → (タブの id, process))
_workers: dict[str, tuple[str, asyncio.subprocess.Process]] = {}
# 通話の終わりを待つ task (= pc_id ごと。 つなぎ直しは、 前の通話の分が終わるのを待つ)
_watchers: dict[str, asyncio.Task] = {}
# タブごとの、 閉じた通話の鳴り残し (= {since_ms, sentences}。 次のつなぎ直しが受け取り、 それ以外の通話は捨てる)
_handovers: dict[str, dict] = {}
# 声の大きさの倍率の上限 (= 端末の画面のつまみの右端。 1 で engine の音のまま)
VOLUME_MAX = 2.0


def _volume_of(raw) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise_error(400, "voice_bad_request", f"volume は 0 から {VOLUME_MAX} の数で渡します")
    if not 0 <= value <= VOLUME_MAX:
        raise_error(400, "voice_bad_request", f"volume は 0 から {VOLUME_MAX} の数で渡します")
    return value


def _with_call_gain(volume: float) -> float:
    """端末のつまみの倍率に、 通話だけの基準 (= `backend/config.json` の `voice_call_gain_db`) を掛ける。 通話は iPhone の
    app の声で、 画面の声とは鳴らし方が違うので、 画面の声を動かさずに通話の大きさだけを揃える口。 読むたびに今の設定。"""
    from backend.config import VOICE_CALL_GAIN_DB  # noqa: PLC0415
    return volume * 10 ** (VOICE_CALL_GAIN_DB / 20)


async def _write(proc: asyncio.subprocess.Process, message: dict) -> None:
    proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
    await proc.stdin.drain()


async def _forget_when_done(pc_id: str, proc: asyncio.subprocess.Process) -> None:
    # 閉じる時の鳴り残しを控える (= 同じタブのつなぎ直しが受け取る)
    while line := await proc.stdout.readline():
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if message.get("type") == "handover" and pc_id in _workers:
            _handovers[_workers[pc_id][0]] = {k: v for k, v in message.items() if k != "type"}
    await proc.wait()
    if _workers.get(pc_id, (None, None))[1] is proc:
        del _workers[pc_id]
        calls_by_conn.pop(pc_id, None)
    _watchers.pop(pc_id, None)
    logger.info("voice call: the call process ended pc_id=%s code=%s", pc_id, proc.returncode)


@router.post("/sessions/{session_id}/voice/call")
async def post_call(request: Request, session_id: str, body: dict = Body(...)) -> dict:
    """接続を申し込む (= SDP の offer を渡し、 answer を受け取る)。

    body: Pipecat の SmallWebRTC の offer (= sdp / type / pc_id / restart_pc)
    query: volume (省略可) = その端末の声の大きさの倍率 (= 0 〜 2。 省けば 1)
           speech (省略可) = 0 なら、 返事を声にしない会話で始める (= 画面の声の入 / 切。 通話中は app が切り替える)
           resume (省略可) = 1 なら、 同じタブの通話のつなぎ直し (= 前の通話が閉じ終えるのを待ち、 鳴り終えていな
                    かった文から言い直す。 閉じた後に届いた返事も声にする)
    """
    volume = _volume_of(request.query_params.get("volume", "1"))
    speech = request.query_params.get("speech", "1") != "0"
    resume = request.query_params.get("resume") == "1"
    # 会話を持てないタブ (= 声を持たない / 聞き取らない) は、 つなぐ前に断る
    settings = conversation_settings(session_id)
    if importlib.util.find_spec("pipecat") is None:
        raise_error(501, "voice_call_unavailable",
                    "この backend には電話の会話の部品が入っていません (= backend/requirements-voice-call.txt)")
    if not isinstance(body.get("sdp"), str) or not isinstance(body.get("type"), str):
        raise_error(400, "voice_bad_request", "本文は SDP の offer (= sdp と type) で渡します")

    # つなぎ直し: 同じタブの前の通話が閉じ終えるのを待ち、 その鳴り残しを受け取る (= つなぎ直しでない通話は、
    # 前の鳴り残しを捨てる)
    if resume:
        ending = [_watchers[pc] for pc, (sid, _) in list(_workers.items()) if sid == session_id and pc in _watchers]
        if ending:
            await asyncio.wait(ending, timeout=ANSWER_TIMEOUT_SECS)
    handover = _handovers.pop(session_id, None)
    host, port = request.scope.get("server") or ("127.0.0.1", 8765)
    start = {
        "type": "start", "base_url": f"http://{host}:{port}", "session_id": session_id,
        "client": f"call-{uuid.uuid4().hex[:12]}", "marks": list(settings["marks"]),
        "conversation": settings["conversation"], "turn": settings["listen"]["turn"],
        "volume": _with_call_gain(volume),
        "speech": speech, "resume": handover if resume else None,
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
    _workers[answer["pc_id"]] = (session_id, proc)
    calls_by_conn[answer["pc_id"]] = session_id   # 通話の間、 このタブへの通知を送らない (= core/push.py)
    _watchers[answer["pc_id"]] = asyncio.create_task(_forget_when_done(answer["pc_id"], proc))
    logger.info("voice call: connecting session=%s pc_id=%s", session_id, answer["pc_id"])
    return answer


@router.patch("/sessions/{session_id}/voice/call")
async def patch_call(session_id: str, body: dict = Body(...)) -> dict:
    """経路の候補を足す。

    body: Pipecat の SmallWebRTC の patch (= pc_id / candidates)
    """
    _, proc = _workers.get(body.get("pc_id") or "", (None, None))
    if proc is None or proc.returncode is not None:
        raise_error(404, "voice_call_unknown", "この接続は見つかりません")
    if not isinstance(body.get("candidates"), list):
        raise_error(400, "voice_bad_request", "本文は pc_id と candidates で渡します")
    await _write(proc, {"type": "patch", "pc_id": body["pc_id"], "candidates": body["candidates"]})
    return {"status": "success"}


@router.post("/sessions/{session_id}/voice/call/volume")
async def post_call_volume(session_id: str, body: dict = Body(...)) -> dict:
    """そのタブの通話の声の大きさの倍率を変える (= 話している途中でもその場で効く)。 通話が無ければ何もしない。

    body:
        volume (number): 0 〜 2 (= 1 で engine の音のまま)
    """
    volume = _volume_of(body.get("volume"))
    calls = [proc for sid, proc in _workers.values() if sid == session_id and proc.returncode is None]
    for proc in calls:
        await _write(proc, {"type": "volume", "volume": _with_call_gain(volume)})
    return {"calls": len(calls)}
