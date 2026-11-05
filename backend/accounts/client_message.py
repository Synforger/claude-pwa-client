"""Sends a tab a message the client wrote itself, starting the tab's claude first when it is asleep or not yet
listening. The same way a message from another tab reaches it (`routes/agent_messages.py`), so that no second way of
waking a tab exists.

Used by `account_fallback/fallback_patrol.py` and `limit_resume/resume_patrol.py`.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException

from backend.routes.agent_messages import wake_tab
from backend.terminal.routes import pty_send

logger = logging.getLogger(__name__)


async def send_to_tab(session_id: str, text: str) -> bool:
    """Type `text` into the tab as a message and press Enter. True when the tab took it; False (with the reason in the
    log) when its claude could not be started or did not take the input."""
    try:
        await wake_tab(session_id)
    except HTTPException as error:
        logger.warning("client message: the tab could not be woken session=%s: %s", session_id, error.detail)
        return False
    result = await pty_send(session_id, {"text": text, "enter": True}, None)
    if not result.get("ok"):
        logger.warning("client message: the tab did not take the message session=%s reason=%s", session_id,
                       result.get("reason"))
    return bool(result.get("ok"))
