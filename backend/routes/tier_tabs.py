"""The endpoint that places a tier tab on request (= `tabs open <tier>`, to bring back a tier tab that was closed).

The backend places the tabs of new tiers by itself (`backend/tier_tabs/tier_tabs.py`). This endpoint places
one for a tier the backend will not place again, because its tab was closed. The tab is a normal tab (= not a
child) like the ones the backend places: no claude runs in it until the first message is sent to it.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Form, Request

from backend._common.errors import raise_error
from backend.routes.agent_messages import LOCAL_CLIENTS
from backend.terminal.tier import parse_tier
from backend.tier_tabs.tier_tabs import agent_for_folder, folder_tiers, place_tab, tab_of

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/tier-tabs")
async def post_tier_tab(request: Request, agent_dir: str = Form(...), tier: str = Form(...)) -> dict:
    """Place a tab for one tier of an agent. → the tab (= one entry of `GET /sessions`).

    form:
        agent_dir (str): the agent's folder (= the `cwd` of one agent in `config.json`)
        tier      (str): `normal`, `projects/<P>` or `projects/<P>/subprojects/<S>` (= a folder of that agent)
    """
    client_host = request.client.host if request.client else None
    if client_host not in LOCAL_CLIENTS:
        logger.warning("tier tab rejected: non-local client=%s", client_host)
        raise_error(403, "tier_tab_local_only", "この口は同じ機械の中からだけ使えます")
    agent_id = agent_for_folder(Path(agent_dir))
    if agent_id is None:
        raise_error(400, "tier_tab_unknown_agent", f"この folder のエージェントが設定にありません: {agent_dir}",
                    agent_dir=agent_dir)
    named = parse_tier(tier.strip())
    if named is None or named not in folder_tiers(Path(agent_dir).expanduser()):
        raise_error(400, "tier_tab_unknown_tier", f"そのエージェントに、 この階層の folder がありません: {tier}", tier=tier)
    held = tab_of(agent_id, named)
    if held is not None:
        raise_error(409, "tier_tab_exists", f"この階層のタブは既にあります: {held}", tier=named, session=held)
    return place_tab(agent_id, named).to_dict()
