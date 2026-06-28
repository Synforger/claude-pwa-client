"""ADR-012 /debug/* endpoint 群。

公開原則 (= 2 段防御、 DNS rebinding 対策、 99-references.md § 12-3):
    1. transport peer が loopback (= 127.0.0.1 / ::1) のみ
    2. Host header allowlist (= localhost / 127.0.0.1 / [::1])

production build でも router を含むが、 上記 2 段で外からは触れない設計。 開発者の手元 PC でだけ
ブラウザの localhost 経由で叩ける。

ADR-020 /debug/e2e/seed は更に CPC_E2E=1 env を要求する 3 段防御。
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.observability import inspector
from backend.observability.event_journal import journal_path, read_range
from backend.observability.metrics import metrics
from backend.observability.replay import replay_stream

router = APIRouter(prefix="/debug")

# DNS rebinding 対策: Host header の host:port が allowlist にあるもののみ通す。
# 開発時の default port (= 8765) と未指定 port (= None 相当) を許可。
ALLOWED_HOST_NAMES = {
    "localhost",
    "127.0.0.1",
    "[::1]",
    "::1",
}

# transport peer (= request.client.host) として許容する loopback 名。 test では starlette
# TestClient が "testclient" を peer に立てるので、 fixture が monkeypatch で本 set に追加する。
# production では loopback 3 種のみ。
ALLOWED_PEERS = {
    "127.0.0.1",
    "::1",
    "localhost",
}


def _host_is_allowed(host_header: str) -> bool:
    """Host header value (= "localhost:8765" 等) を分解して allowlist と照合。

    port は問わない (= 開発者が configure した backend port は任意で OK)。 host name の正確な
    一致のみを要求する。
    """
    if not host_header:
        return False
    host = host_header.strip().lower()
    # [::1]:port 形式と localhost:port 形式の両対応
    if host.startswith("["):
        # IPv6 bracket
        end = host.find("]")
        if end == -1:
            return False
        name = host[: end + 1]
    else:
        # 最後の ':' を port 区切りと見なす (= IPv4 / 名前 / 素の ::1 を扱う)
        if ":" in host and host.count(":") == 1:
            name = host.rsplit(":", 1)[0]
        else:
            name = host
    return name in ALLOWED_HOST_NAMES


def _ensure_localhost(request: Request) -> None:
    """2 段 check (= loopback peer + Host allowlist)。 違反は 403。"""
    client = request.client
    peer = client.host if client else None
    if peer not in ALLOWED_PEERS:
        raise HTTPException(status_code=403, detail="debug endpoints are localhost-only")
    host_header = request.headers.get("host", "")
    if not _host_is_allowed(host_header):
        raise HTTPException(status_code=403, detail=f"host not allowed: {host_header}")


@router.get("/state")
async def get_state(request: Request) -> dict[str, Any]:
    _ensure_localhost(request)
    return inspector.snapshot()


@router.get("/metrics")
async def get_metrics(request: Request) -> dict[str, Any]:
    _ensure_localhost(request)
    return metrics.snapshot()


@router.get("/log")
async def get_log(
    request: Request,
    sid: str | None = None,
    start_ts: float | None = None,
    end_ts: float | None = None,
    days_back: int = 1,
    limit: int = 500,
) -> dict[str, Any]:
    """直近 event_journal entry を時刻範囲 + sid で filter して返す (= 単発 JSON)。

    巨大 response 防止のため `limit` (= default 500、 最新を返す)。 streaming で見たい時は
    /debug/replay を使う。
    """
    _ensure_localhost(request)
    entries = read_range(start_ts=start_ts, end_ts=end_ts, sid=sid, days_back=days_back)
    entries.sort(key=lambda e: e.get("seq", 0))
    return {
        "count": len(entries),
        "returned": min(limit, len(entries)),
        "journal_path": str(journal_path()),
        "entries": entries[-limit:],
    }


class ReplayRequest(BaseModel):
    sid: str | None = None
    start_ts: float | None = None
    end_ts: float | None = None
    speed: float = 0.0
    days_back: int = 1


@router.post("/replay")
async def post_replay(request: Request, body: ReplayRequest) -> StreamingResponse:
    """event_journal を SSE で再配信。 frontend debug panel が直接 EventSource で接続する想定。"""
    _ensure_localhost(request)
    return StreamingResponse(
        replay_stream(
            sid=body.sid,
            start_ts=body.start_ts,
            end_ts=body.end_ts,
            speed=body.speed,
            days_back=body.days_back,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ----- ADR-020 e2e seed endpoint ---------------------------------------------
# Bypasses hook-driven binding (= claude SessionStart hook) so playwright can
# install a session + JSONL fixture in one POST. Triple-gated: localhost peer,
# Host allowlist, and CPC_E2E=1 must be set in the backend process env. The
# router stays registered in prod builds so any env mistake fails closed (= 404
# without the env), matching the rest of /debug/*.


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
    from backend.state import SessionDef, save_sessions_meta, sessions_meta

    agents = (await _agents_snapshot())
    if body.agent_id not in agents:
        raise HTTPException(status_code=400, detail=f"unknown agent_id: {body.agent_id}")
    agent_cwd = agents[body.agent_id].get("cwd") or str(Path.home())

    claude_sid = body.claude_sid or str(uuid.uuid4())
    projects_dir = projects_dir_for_account(body.account_id)
    cwd_hash = watcher._cwd_to_project_dirname(agent_cwd)
    jsonl_dir = projects_dir / cwd_hash
    jsonl_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = jsonl_dir / f"{claude_sid}.jsonl"

    with jsonl_path.open("w", encoding="utf-8") as f:
        for event in body.jsonl_events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    sessions_meta[body.sid] = SessionDef(
        id=body.sid,
        agent_id=body.agent_id,
        title=body.title or body.sid,
        created_at=int(time.time()),
        notify_mode=body.notify_mode if body.notify_mode in {"off", "banner", "both"} else "both",
        account_id=body.account_id,
    )
    save_sessions_meta()

    watcher.confirm_bind(body.sid, claude_sid, str(jsonl_path))

    return E2eSeedResponse(
        sid=body.sid,
        claude_sid=claude_sid,
        jsonl_path=str(jsonl_path),
        written_events=len(body.jsonl_events),
    )


async def _agents_snapshot() -> dict[str, dict[str, Any]]:
    # Tiny indirection so the test suite can monkeypatch agent config without
    # reaching into backend.config internals.
    from backend.config import AGENTS  # noqa: PLC0415
    return AGENTS
