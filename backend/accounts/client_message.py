"""Sends a tab a message the client wrote itself, starting the tab's claude first when it is asleep or not yet
listening. The same way a message from another tab reaches it (`routes/agent_messages.py`), so that no second way of
waking a tab exists.

Used by `account_fallback/fallback_patrol.py` and `limit_resume/resume_patrol.py`.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException

from backend.routes.agent_messages import deliver_message, wake_tab

logger = logging.getLogger(__name__)


async def send_to_tab(session_id: str, text: str) -> bool:
    """Type `text` into the tab as a message and press Enter. True when the tab took it; False (with the reason in the
    log) when its claude could not be started or did not take the message."""
    try:
        woke = await wake_tab(session_id)
        result = await deliver_message(session_id, text, woke)
    except HTTPException as error:
        logger.warning("client message: the tab did not take the message session=%s: %s", session_id, error.detail)
        return False
    if not result.get("ok"):
        logger.warning("client message: the tab did not take the message session=%s reason=%s", session_id,
                       result.get("reason"))
    return bool(result.get("ok"))
