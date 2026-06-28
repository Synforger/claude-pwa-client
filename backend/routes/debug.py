"""ADR-012 /debug/* endpoint 群。

公開原則 (= 2 段防御、 DNS rebinding 対策、 99-references.md § 12-3):
    1. transport peer が loopback (= 127.0.0.1 / ::1) のみ
    2. Host header allowlist (= localhost / 127.0.0.1 / [::1])

production build でも router を含むが、 上記 2 段で外からは触れない設計。 開発者の手元 PC でだけ
ブラウザの localhost 経由で叩ける。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

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
