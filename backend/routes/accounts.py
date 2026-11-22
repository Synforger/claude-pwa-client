"""accounts / agents 選択肢 endpoint (= 旧 chat.py から分割、 backend-F-28 / crosscut-F-04)。

セッション作成 UI の選択肢を返すだけの薄い router。
- GET /agents    : agent 種別 (作成時 agent_id 選択肢)
- GET /accounts  : OAuth account (個人 / 会社、 候補 1 つなら frontend 側で hide)
"""
from __future__ import annotations

from fastapi import APIRouter

from backend._common import config as _config
from backend._common.agent_roles import child_agent_ids, is_offered_for_new_tab
from backend._common.list_folder import parse_list_folder

router = APIRouter()


@router.get("/agents")
def list_agents():
    """セッション作成時の選択肢として agent 種別一覧を返す。 `list_folder` は、 一覧でそのエージェントのタブを並べる
    folder (= `<agent の id>/<folder>/...`) で、 書いてあるエージェントにだけ付く。 `offered_for_new_tab` は、 新しい会話の
    選択に出さないエージェントにだけ false で付く。 一覧の名前と folder に要るので、 そのエージェントも返す。"""
    agents = _config.AGENTS
    child_ids = child_agent_ids(agents)
    return [_agent_view(name, cfg, child_ids) for name, cfg in agents.items()]


def _agent_view(name: str, cfg: dict, child_ids: set[str]) -> dict:
    view = {"id": name, "display_name": cfg.get("display_name", name.upper())}
    folder = parse_list_folder(cfg.get("list_folder"))
    if folder is not None:
        view["list_folder"] = folder
    if not is_offered_for_new_tab(name, cfg, child_ids):
        view["offered_for_new_tab"] = False
    return view


@router.get("/accounts")
def list_accounts():
    """セッション作成時の「アカウント」 (= 個人 / 会社 OAuth 切替) 選択肢を返す。
    候補が 1 つ (= 通常 personal だけ) のとき、 frontend は選択肢自体を出さなくて良い。
    """
    from backend._common.config import ACCOUNTS, default_account_id  # noqa: PLC0415
    # account_id を持たない session (= 古い時期に作られたタブ) がどの account と等価かを
    # frontend が判定できるよう、 既定 account に印を付ける。 これが無いと「所属なし」 扱いに
    # なり、 自分自身が「別アカウントで続ける」 の候補に並ぶ。
    default_id = default_account_id()
    return [
        {
            "id": name,
            "display_name": cfg.get("display_name", name),
            "is_default": name == default_id,
        }
        for name, cfg in ACCOUNTS.items()
    ]
