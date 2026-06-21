"""accounts / agents 選択肢 endpoint (= 旧 chat.py から分割、 backend-F-28 / crosscut-F-04)。

セッション作成 UI の選択肢を返すだけの薄い router。
- GET /agents    : agent 種別 (作成時 agent_id 選択肢)
- GET /accounts  : OAuth account (個人 / 会社、 候補 1 つなら frontend 側で hide)
"""
from __future__ import annotations

from fastapi import APIRouter

from backend.config import AGENTS

router = APIRouter()


@router.get("/agents")
def list_agents():
    """セッション作成時の選択肢として agent 種別一覧を返す。"""
    return [
        {"id": name, "display_name": cfg.get("display_name", name.upper())}
        for name, cfg in AGENTS.items()
    ]


@router.get("/accounts")
def list_accounts():
    """セッション作成時の「アカウント」 (= 個人 / 会社 OAuth 切替) 選択肢を返す。
    候補が 1 つ (= 通常 personal だけ) のとき、 frontend は選択肢自体を出さなくて良い。
    """
    from backend.config import ACCOUNTS  # noqa: PLC0415
    return [
        {"id": name, "display_name": cfg.get("display_name", name)}
        for name, cfg in ACCOUNTS.items()
    ]
