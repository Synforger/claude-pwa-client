"""POST /accounts/{account}/continue: continues the tabs the account hold stopped on the account (= the operator asks
for it from the settings screen). Each stopped tab is sent the message that asks it to carry on, which wakes it in the
same conversation, and loses its mark (`backend/account_hold/hold_continue.py`).

The answer is 409 while the usage of the account is still at the line of today, and 404 for an account that is not in the
configuration.
"""
from __future__ import annotations

from fastapi import APIRouter

import backend._common.config as config
from backend._common.errors import raise_error
from backend.account_hold import StillAtLine, continue_account

router = APIRouter()


@router.post("/accounts/{account}/continue")
async def continue_held_tabs(account: str) -> dict:
    if account not in config.ACCOUNTS:
        raise_error(404, "unknown_account", "そのアカウントは設定にありません")
    try:
        result = await continue_account(account)
    except StillAtLine as error:
        raise_error(409, "still_at_line", "使用率がまだ止める線以上なので、 続けられません", line_pct=error.line_pct)
    return {"continued": list(result.continued), "failed": list(result.failed)}
