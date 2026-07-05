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
import json
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.routes.debug import _ensure_localhost

router = APIRouter(prefix="/debug")


def _ensure_e2e_enabled() -> None:
    if os.environ.get("CPC_E2E") != "1":
        raise HTTPException(status_code=404, detail="not found")


class E2eSeedRequest(BaseModel):
    sid: str = Field(..., description="pwa session id (= ses_xxx)")
    agent_id: str = Field("agent_e2e", description="must exist in config.agents")
    account_id: str | None = Field(None, description="resolves the claude projects dir")
    title: str | None = None
    notify_mode: str = Field("both", description="off | banner | both")
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
    from backend.config import projects_dir_for_account
    from backend.jsonl import watcher
    from backend.state import register_session, sessions_meta

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
    register_session(
        agent_id=body.agent_id,
        title=body.title or body.sid,
        account_id=body.account_id,
        sid=body.sid,
    )
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
    from backend.state import agent_status, sessions_overview
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
    # reaching into backend.config internals.
    from backend.config import AGENTS  # noqa: PLC0415
    return AGENTS
