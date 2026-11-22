"""Tells the tab that wrote a kept message what became of it. Only a tab whose claude is running is told, and it is not
woken for this: a notice that finds the tab asleep or closed stays in the backend's log. The notice hands the tab no
work (= a parent's child is not set back to working by it).

Used by `outbox_flush.py`.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException

from backend._common.state import sessions_meta
from backend._internal.stop_signal import BackendStopping

logger = logging.getLogger(__name__)


async def notify_sender(entry: dict, notice: str) -> bool:
    """Type `notice` into the tab that wrote the kept message `entry`. True when the tab took it; False (with the notice
    in the log) when that tab is gone, has no claude running, or did not take it."""
    # Imported here: the message routes use this package to send to another machine.
    from backend.routes.agent_messages import _tab_running, deliver_message  # noqa: PLC0415
    tab_id = entry["from_session"]
    if tab_id not in sessions_meta or not _tab_running(tab_id):
        logger.info("kept message %s to %s:%s: its sender %s is not running, so it was not told: %s",
                    entry["id"], entry["peer"], entry["to"], tab_id, notice.splitlines()[-2])
        return False
    try:
        result = await deliver_message(tab_id, notice, woke=False)
    except HTTPException as error:
        logger.warning("kept message %s: its sender %s did not take the notice: %s", entry["id"], tab_id, error.detail)
        return False
    except BackendStopping:
        logger.info("kept message %s: the backend is stopping; its sender %s was not waited for", entry["id"], tab_id)
        return False
    return bool(result.get("ok"))
