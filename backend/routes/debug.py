"""ADR-012 /debug/* の observability endpoint 群 (= state / metrics)。

公開原則 (= 2 段防御、 DNS rebinding 対策、 99-references.md § 12-3):
    1. transport peer が loopback (= 127.0.0.1 / ::1) のみ
    2. Host header allowlist (= localhost / 127.0.0.1 / [::1])

production build でも router を含むが、 上記 2 段で外からは触れない設計。 開発者の手元 PC でだけ
ブラウザの localhost 経由で叩ける。

/debug/* は防御レベル別に 3 file 分割 (= 本 file が 2 段防御 guard の真値):
    - 本 file: observability (= 2 段防御のみ)
    - `debug_healthcheck.py`: /debug/healthcheck (= 同じ 2 段防御、 read-only probe 12 種)
    - `debug_e2e.py`: /debug/e2e/* (= 2 段 + CPC_E2E=1 env の 3 段防御、 e2e harness 専用)
"""
from __future__ import annotations

import asyncio
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
from backend.observability.metrics import metrics

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
