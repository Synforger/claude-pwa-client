"""Sends a tab a message the client wrote itself, starting the tab's claude first when it is asleep or not yet
listening. The same way a message from another tab reaches it (`routes/agent_messages.py`), so that no second way of
waking a tab exists. A tab set up for a program to ask (`"ask": true`) is never typed into: the program asks again
itself, and a "carry on" there would answer a question already given up and take the next ask's `Stop`.

Used by the patrols that write to tabs: `account_fallback/`, `account_hold/`, `limit_resume/` and `child_watch/`.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException

from backend.routes.agent_messages import deliver_message, wake_tab
from backend.terminal.session_resolver import takes_asks

logger = logging.getLogger(__name__)


async def send_to_tab(session_id: str, text: str) -> bool:
    """Type `text` into the tab as a message and press Enter. True when the tab took it; False (with the reason in the
    log) when its claude could not be started or did not take the message. A tab set up for asks is left as it is
    and counts as told (True), so that no sender keeps a debt to it."""
    if takes_asks(session_id):
        logger.info("client message: not typed into a tab set up for asks session=%s", session_id)
        return True
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
