"""The error resume patrol: looks over the tabs on the rollover's interval and, for a tab whose turn a passing API error
ended, types one message to carry on; when those messages do not get it going, tells the tab's parent (a child) or the
operator (any other tab) once. A tab asleep is woken by the message, in the same conversation. See
`docs/reference/error-resume.md`.

The judgement is `error_judgement.py`, read through `error_sensors.py`. A tab found due is claimed, and read and judged
again inside the claim, since another feature may have sent it a message in between. The message is marked in the
tab's definition after sending returns, with how many times it was sent for the same error row, so neither a later look
nor a restart sends it again until the time for it to show in the record has passed.
"""
from __future__ import annotations

import asyncio
import logging
import time

from backend._common.state import ErrorResumeMark, SessionDef, save_sessions_meta, sessions_meta
from backend.accounts.client_message import send_to_tab
from backend.accounts.tab_claim import claimed
from backend.child_watch.watch_judgement import API_ERROR
from backend.child_watch.watch_patrol import tell_parent
from backend.error_resume.error_envelope import gave_up_words, resume_envelope
from backend.error_resume.error_judgement import GIVE_UP, SEND
from backend.error_resume.error_sensors import ErrorLook, look_at_tab
from backend.push.push import broadcast_push, notification_title_for
from backend.rollover.rollover import TICK_SEC
from backend.sleep.record_facts import ErrorStop
from backend.usage.usage import read_all_rate_limits_tail

logger = logging.getLogger(__name__)


def _sent_count(meta: SessionDef, stop: ErrorStop) -> int:
    """How many times the message was sent for `stop` so far."""
    mark = meta.error_resumed
    return mark.sent_count if mark is not None and mark.stop == stop.uuid else 0


async def _send(meta: SessionDef, stop: ErrorStop, streak: int) -> bool:
    """Type the message to carry on, and mark it, whether the tab took it or not (a message that keeps failing is
    counted towards giving up like one that never shows in the record). True when the tab took it."""
    sent = await send_to_tab(meta.id, resume_envelope(stop, streak))
    meta.error_resumed = ErrorResumeMark(stop=stop.uuid, sent_at=time.time(), sent_count=_sent_count(meta, stop) + 1)
    save_sessions_meta()
    logger.info("error resume: session=%s stop=%s cause=%s streak=%d asleep=%d sent=%s sent_count=%d", meta.id,
                stop.uuid, stop.cause, streak, meta.sleep is not None, sent, meta.error_resumed.sent_count)
    return sent


async def _give_up(meta: SessionDef, stop: ErrorStop, look: ErrorLook) -> None:
    """Stop carrying the tab on, and tell its parent (a child) or the operator (any other tab) once."""
    meta.error_gave_up = stop.uuid               # before telling: a restart must not tell it twice
    save_sessions_meta()
    sent_count = _sent_count(meta, stop)
    if meta.child and meta.parent_id in sessions_meta and look.last_row_at is not None:
        told = "parent" if await tell_parent(meta, look.last_row_at, API_ERROR) else "nobody"
    else:
        await broadcast_push(gave_up_words(stop, max(sent_count, look.streak)), notification_title_for(meta.id),
                             meta.id)
        told = "operator"
    logger.info("error resume: gave up session=%s stop=%s streak=%d sent_count=%d told=%s", meta.id, stop.uuid,
                look.streak, sent_count, told)


async def _look(session_id: str, rows: list[dict]) -> str | None:
    """Look at one tab and act on it when it is due. → the answer acted on (`SEND` / `GIVE_UP`), None when nothing was
    done."""
    meta = sessions_meta.get(session_id)
    if meta is None:
        return None
    look = await asyncio.to_thread(look_at_tab, meta, time.time(), rows)
    if look.answer not in (SEND, GIVE_UP):
        return None
    with claimed(session_id) as mine:
        if not mine:
            return None
        look = await asyncio.to_thread(look_at_tab, meta, time.time(), rows)
        if look.stop is None:
            return None
        if look.answer == SEND:
            await _send(meta, look.stop, look.streak)
            return SEND
        if look.answer == GIVE_UP:
            await _give_up(meta, look.stop, look)
            return GIVE_UP
    return None


async def tick() -> dict[str, str]:
    """Look over every tab once. → the tabs acted on, with the answer acted on."""
    rows = await asyncio.to_thread(read_all_rate_limits_tail)
    acted: dict[str, str] = {}
    for session_id in list(sessions_meta):
        answer = await _look(session_id, rows)
        if answer is not None:
            acted[session_id] = answer
    return acted


async def resume_loop(interval_sec: float = TICK_SEC) -> None:
    """Look over the tabs every `interval_sec` (= the rollover's interval)."""
    logger.info("error resume loop started (interval=%ds)", interval_sec)
    try:
        while True:
            await asyncio.sleep(interval_sec)
            try:
                await tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("error resume loop iteration failed")
    except asyncio.CancelledError:
        logger.info("error resume loop cancelled")
        raise
