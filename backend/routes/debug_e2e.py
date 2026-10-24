"""ADR-020 /debug/e2e/* endpoint 群 (= playwright e2e harness 専用の seed / injection)。

Bypasses hook-driven binding (= claude SessionStart hook) so playwright can
install a session + JSONL fixture in one POST.

公開原則 = 3 段防御: /debug/* 共通の 2 段 (= loopback peer + Host allowlist、
`debug._ensure_localhost` を共用) に加えて **CPC_E2E=1 env を要求**する。 router は
prod build にも登録されたままだが、 env が無ければ全 endpoint が 404 に倒れる
(= fail closed)。 本番運用の probe (= /debug/healthcheck) や observability
(= /debug/state 等) とは防御レベルが違うので file を分離してある。
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import uuid
import wave
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from backend.routes.debug import _ensure_localhost
from backend.terminal.tab_tier import set_tier
from backend.terminal.tier import parse_tier

router = APIRouter(prefix="/debug")
# 拡張の口の e2e 用 fixture (= 本番では Tailscale Serve が載せる `/ext/<id>/` を test backend が代わりに
# 返す)。 `/debug` の外に置く必要があるので router を分けるが、 防御は同じ 3 段。
fixture_router = APIRouter()


def _ensure_e2e_enabled() -> None:
    if os.environ.get("CPC_E2E") != "1":
        raise HTTPException(status_code=404, detail="not found")


class E2eSeedRequest(BaseModel):
    sid: str = Field(..., description="pwa session id (= ses_xxx)")
    agent_id: str = Field("agent_e2e", description="must exist in config.agents")
    account_id: str | None = Field(None, description="resolves the claude projects dir")
    title: str | None = None
    notify_mode: str = Field("both", description="off | banner | both")
    parent_id: str | None = Field(None, description="the tab this one hangs under in the drawer (= a fork or a child)")
    child: bool = Field(False, description="a child tab (= opened by another tab's agent)")
    tier: str | None = Field(None, description="the tier the tab's agent started in (= what its AGENT_TIER would say)")
    claude_sid: str | None = Field(
        None,
        description="filename stem under <projects>/<cwd-hash>/; UUID4 if omitted",
    )
    jsonl_events: list[dict[str, Any]] = Field(
        default_factory=list,
        description="ordered JSONL events; written verbatim, one per line",
    )


class E2eSeedResponse(BaseModel):
    sid: str
    claude_sid: str
    jsonl_path: str
    written_events: int


@router.post("/e2e/seed", response_model=E2eSeedResponse)
async def post_e2e_seed(request: Request, body: E2eSeedRequest) -> E2eSeedResponse:
    """Seed a session_meta entry + JSONL fixture + confirmed binding in one go.

    Mirrors what `POST /sessions` + claude SessionStart hook would do, but
    without spawning tmux / claude. Playwright global-setup calls this once per
    fixture session.
    """
    _ensure_localhost(request)
    _ensure_e2e_enabled()

    # Imports are local so prod builds never load these modules unless e2e is
    # actually exercised (= keeps startup graph clean + dodges a state.py side
    # effect for non-e2e processes).
    from backend._common.config import projects_dir_for_account
    from backend.jsonl import history as session_history
    from backend.jsonl import jsonl_watcher as watcher
    from backend.jsonl.routes import request_sid_tail_reset
    from backend._common.state import register_session, sessions_meta

    agents = (await _agents_snapshot())
    if body.agent_id not in agents:
        raise HTTPException(status_code=400, detail=f"unknown agent_id: {body.agent_id}")
    agent_cwd = agents[body.agent_id].get("cwd") or str(Path.home())

    claude_sid = body.claude_sid or str(uuid.uuid4())
    projects_dir = projects_dir_for_account(body.account_id)
    # Safety net: refuse to write into the operator's real ~/.claude/projects.
    # The launcher is supposed to point the e2e account at an isolated dir
    # (= fixtures/_runtime/.claude); if it didn't, fail loud instead of
    # silently scattering fixture JSONL into live chat history.
    real_home_claude = (Path.home() / ".claude" / "projects").resolve()
    if projects_dir.resolve() == real_home_claude:
        raise HTTPException(
            status_code=400,
            detail=(
                "refusing to seed into the real ~/.claude/projects. "
                "Set accounts.<account>.env.CLAUDE_CONFIG_DIR to an isolated dir."
            ),
        )
    cwd_hash = watcher._cwd_to_project_dirname(agent_cwd)
    jsonl_dir = projects_dir / cwd_hash
    jsonl_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = jsonl_dir / f"{claude_sid}.jsonl"

    with jsonl_path.open("w", encoding="utf-8") as f:
        for event in body.jsonl_events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    # Re-seeding the same sid is idempotent: drop the previous registration so
    # register_session reinitialises every companion dict (stream_states /
    # agent_status / session_states), matching what a fresh /sessions POST
    # would produce.
    if body.sid in sessions_meta:
        sessions_meta.pop(body.sid, None)
    # 前の seed の記録は、 新しい記録へ結び直すと「終わった会話」 として控えに積まれ、 履歴がつないで
    # 出し続ける (= 入れ替えと同じ扱い)。 seed は新しいタブなので、 控えを消し、 見張りにも前の記録を
    # 忘れさせる (= 次の見張りが path の切り替わりを見て、 控えに積み直さない)。
    session_history.forget(body.sid)
    request_sid_tail_reset(body.sid)
    register_session(
        agent_id=body.agent_id,
        title=body.title or body.sid,
        account_id=body.account_id,
        sid=body.sid,
        parent_id=body.parent_id,
        child=body.child,
    )
    set_tier(body.sid, parse_tier(body.tier))
    # notify_mode override (register_session leaves it at "both" by default).
    if body.notify_mode in {"off", "banner", "both"}:
        sessions_meta[body.sid].notify_mode = body.notify_mode

    watcher.confirm_bind(body.sid, claude_sid, str(jsonl_path))

    return E2eSeedResponse(
        sid=body.sid,
        claude_sid=claude_sid,
        jsonl_path=str(jsonl_path),
        written_events=len(body.jsonl_events),
    )


class PendingPlanInjectRequest(BaseModel):
    plan: str = Field("e2e plan body")
    tool_use_id: str = Field("tool_e2e_plan")
    choices: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/e2e/working/{session_id}")
async def post_e2e_working(request: Request, session_id: str, working: bool = Body(..., embed=True)) -> dict:
    """session を「claude が作業中」 にする / 戻す。 作業中の間、 画面からの送信は claude と同じく
    user 行を書かず、 積んだ記録 (= queue-operation の enqueue) だけを残す。"""
    _ensure_localhost(request)
    _ensure_e2e_enabled()
    from backend.terminal.routes import set_e2e_working  # noqa: PLC0415
    set_e2e_working(session_id, working)
    return {"ok": True, "working": working}


@router.post("/e2e/forget-sends")
async def post_e2e_forget_sends(request: Request) -> dict:
    """送信の identity (= send_id) の控えを全部忘れる。 本番では送ってから 60 秒で忘れる (= TTL) ので、
    claude が長く作業した後に受け取った発話には send_id が付かない。 その状態を待たずに作る。"""
    _ensure_localhost(request)
    _ensure_e2e_enabled()
    from backend.terminal.send_dedup import send_dedup  # noqa: PLC0415
    send_dedup.reset()
    return {"ok": True}


@router.post("/e2e/inject-pending-plan/{session_id}")
async def post_e2e_inject_pending_plan(
    request: Request,
    session_id: str,
    body: PendingPlanInjectRequest,
) -> dict:
    """ADR-022 follow-up: write pending_plan straight into agent_status[sid].

    The status SSE pump reads from agent_status, so the next tick delivers
    the change to whatever client is subscribed - same path as the real
    capture_plan_choices result but without needing a tmux pane.
    """
    _ensure_localhost(request)
    _ensure_e2e_enabled()
    from backend._common.state import agent_status, sessions_overview
    if session_id not in agent_status:
        raise HTTPException(status_code=409, detail="no session")
    agent_status[session_id]["pending_plan"] = {
        "tool_use_id": body.tool_use_id,
        "plan": body.plan,
        "choices": body.choices,
    }
    # Wake the /sessions/status/stream broadcaster so subscribers get the new
    # snapshot on the next event loop tick instead of waiting for the 20s
    # keep-alive to roll around.
    sessions_overview.notify()
    return {"ok": True}


class PtyWriteRequest(BaseModel):
    bytes_b64: str = Field(..., description="base64-encoded bytes to enqueue on the WS output side")


@router.post("/e2e/pty-write/{session_id}")
async def post_e2e_pty_write(request: Request, session_id: str, body: PtyWriteRequest) -> dict:
    """ADR-022 e2e WS injection: enqueue bytes on a fake PTY session's output queue.

    The websocket /ws/pty/{sid} handler in CPC_E2E mode skips spawn and
    installs a queue-only PtySession; pump_to_client then forwards anything
    we put on the queue to every attached client. Scenarios use this to
    drive UTF-8 boundary tests, ANSI tests, etc., without booting a real PTY.
    """
    import base64
    _ensure_localhost(request)
    _ensure_e2e_enabled()
    from backend.terminal.runner import pty_sessions
    session = pty_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=409, detail="no pty session (= /ws/pty not connected yet?)")
    try:
        data = base64.b64decode(body.bytes_b64, validate=True)
    except (ValueError, Exception) as exc:
        raise HTTPException(status_code=400, detail=f"bad base64: {exc}") from exc
    try:
        session.output_queue.put_nowait(data)
    except asyncio.QueueFull:
        raise HTTPException(status_code=503, detail="pty queue full") from None
    return {"ok": True, "queued": len(data)}


async def _agents_snapshot() -> dict[str, dict[str, Any]]:
    # Tiny indirection so the test suite can monkeypatch agent config without
    # reaching into backend._common.config internals.
    from backend._common.config import AGENTS  # noqa: PLC0415
    return AGENTS


# 拡張の fixture。 読み込まれた時刻を画面に出すので、 scenario は「畳んで開き直しても同じ文書が
# 生きている (= iframe が破棄されていない)」 をこの値の一致で確かめられる。
_EXTENSION_FIXTURE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Fixture extension</title></head>
<body style="background:#000;color:#fff;margin:0">
<p id="born"></p>
<script>document.getElementById('born').textContent = String(performance.timeOrigin)</script>
</body></html>
"""


# `/ext/fixture-page/` は、 頁として開く拡張 (= config の `view: "page"`) の fixture。 中身は同じ 1 枚。
@fixture_router.api_route("/ext/fixture/", methods=["GET", "HEAD"], include_in_schema=False)
@fixture_router.api_route("/ext/fixture-page/", methods=["GET", "HEAD"], include_in_schema=False)
async def e2e_extension_fixture(request: Request) -> HTMLResponse:
    """e2e の拡張 fixture (= 静的 HTML 1 枚)。 CPC_E2E=1 かつ loopback の時だけ返す。"""
    _ensure_localhost(request)
    _ensure_e2e_enabled()
    return HTMLResponse(_EXTENSION_FIXTURE_HTML)


# 声の口の e2e 用 fixture (= 本番では別の process が持つ音声合成の engine を、 test backend が代わりに返す)。
# 問い合わせには engine と同じ形の値を、 合成には無音の短い WAV を返す。 `text` が `[fail]` で始まる文の
# 合成は断る (= engine が失敗した時の画面を scenario が見るための口)。
_VOICE_FIXTURE_SECONDS = 0.2
_VOICE_FIXTURE_RATE = 8000


def _silence() -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_VOICE_FIXTURE_RATE)
        w.writeframes(b"\x00\x00" * int(_VOICE_FIXTURE_RATE * _VOICE_FIXTURE_SECONDS))
    return out.getvalue()


@fixture_router.post("/ext/fixture-voice/audio_query", include_in_schema=False)
async def e2e_voice_fixture_query(request: Request, text: str, speaker: int) -> dict:
    """e2e の音声合成の fixture: 問い合わせ。 CPC_E2E=1 かつ loopback の時だけ返す。"""
    _ensure_localhost(request)
    _ensure_e2e_enabled()
    return {"accent_phrases": [], "speedScale": 1.0, "pitchScale": 0.0, "intonationScale": 1.0,
            "prePhonemeLength": 0.1, "kana": text}


@fixture_router.post("/ext/fixture-voice/synthesis", include_in_schema=False)
async def e2e_voice_fixture_synthesis(request: Request, speaker: int, query: dict = Body(...)) -> Response:
    """e2e の音声合成の fixture: 合成。 CPC_E2E=1 かつ loopback の時だけ返す。"""
    _ensure_localhost(request)
    _ensure_e2e_enabled()
    if str(query.get("kana", "")).startswith("[fail]"):
        raise HTTPException(status_code=500, detail="the fixture engine was asked to fail")
    return Response(content=_silence(), media_type="audio/wav")


# 聞き取りの e2e 用 fixture (= 本番では別の process が持つ whisper-server を、 test backend が代わりに返す)。
# 音を受けたら、 決まった 1 文を、 engine と同じく区切りの改行つきで返す (= 中身は聞かない)。
VOICE_FIXTURE_HEARD = "what the fixture heard"


@fixture_router.post("/ext/fixture-listen/inference", include_in_schema=False)
async def e2e_listen_fixture_inference(
    request: Request, file: UploadFile = File(...), response_format: str = Form("json"),
) -> dict:
    """e2e の聞き取りの fixture。 CPC_E2E=1 かつ loopback の時だけ返す。"""
    _ensure_localhost(request)
    _ensure_e2e_enabled()
    if not await file.read():
        raise HTTPException(status_code=400, detail="the fixture engine was given no sound")
    return {"text": f" {VOICE_FIXTURE_HEARD}\n"}
