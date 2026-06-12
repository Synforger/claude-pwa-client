"""個人 / 仕事 Claude OAuth credentials の切替エンドポイント。

GET  /account             現在の profile と利用可能 profile を返す
POST /account/switch      body: {target: "personal"|"work"} → credentials 差し替え +
                          全 PTY 強制再起動 (= 既存 jsonl はそのまま、 新アカウントで claude が再起動)
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, HTTPException

from account_switch import (
    PROFILE_SERVICES,
    available_profiles,
    current_profile,
    switch_profile,
)
from state import sessions_meta
from terminal.runner import kill_tmux_session

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/account")
def get_account():
    return {
        "profile": current_profile(),
        "available": available_profiles(),
        "all": list(PROFILE_SERVICES.keys()),
    }


@router.post("/account/switch")
def post_switch(payload: dict = Body(...)):
    target = payload.get("target")
    if target not in PROFILE_SERVICES:
        raise HTTPException(status_code=400, detail=f"target must be one of {list(PROFILE_SERVICES)}")
    result = switch_profile(target)
    if not result.get("changed"):
        return result
    # 切替成功時は全 tmux session を kill → autoresume 経路で新 credentials を使った claude が
    # 既存 jsonl を resume して再起動する。
    killed = 0
    for sid in list(sessions_meta.keys()):
        try:
            if kill_tmux_session(sid):
                killed += 1
        except Exception:
            logger.exception("kill_tmux_session failed sid=%s", sid)
    logger.info("account switch: target=%s killed=%d", target, killed)
    return {**result, "killed_sessions": killed}
