"""The limit resume patrol: looks over the tabs on the rollover's interval and, for a tab whose turn a usage limit
stopped, sends one message to carry on once the limit of its account is over. A tab asleep is woken by that message,
in the same conversation. See `docs/reference/limit-resume.md`.

The judgement is `resume_judgement.py`. One stop is answered once: the uuid of the stop is kept in the tab's
definition before the message is sent, so neither a second look nor a restart of the backend sends it again.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import backend.jsonl.jsonl_watcher as jsonl_watcher
from backend._common.config import default_account_id
from backend._common.state import SessionDef, save_sessions_meta, sessions_meta
from backend.account_fallback.fallback_settings import read_rules
from backend.accounts.client_message import send_to_tab
from backend.accounts.tab_claim import claimed
from backend.limit_resume.resume_envelope import resume_envelope
from backend.limit_resume.resume_judgement import NO_FALLBACK_LINE_PCT, should_resume
from backend.rollover.rollover import TICK_SEC
from backend.sleep.record_facts import LimitStop
from backend.sleep.sleep_sensors import record_facts_of
from backend.terminal.pty_discover import claude_pid_in_pane
from backend.usage.limit_state import limit_state
from backend.usage.usage import read_all_rate_limits_tail

logger = logging.getLogger(__name__)

# The stop (its uuid) of each tab that was seen while its account was at the line. Memory only: a stop the usage
# explains by a reset after it does not need it.
_seen_at_limit: dict[str, str] = {}


def _stop_of(meta: SessionDef) -> LimitStop | None:
    """The usage-limit stop the tab's conversation ends in. Blocking."""
    record = Path(meta.sleep.record) if meta.sleep is not None else jsonl_watcher.get_jsonl_for(meta.id)
    if record is None:
        return None
    try:
        return record_facts_of(record).limit_stop
    except OSError:
        return None


async def _look(session_id: str, rows: list[dict], now: float) -> bool:
    """Look at one tab and tell it to carry on if its stop is over. True when the message was sent."""
    meta = sessions_meta.get(session_id)
    if meta is None:
        return False
    stop = await asyncio.to_thread(_stop_of, meta)
    if stop is None:
        _seen_at_limit.pop(session_id, None)
        return False
    if meta.limit_resumed == stop.uuid:
        return False
    account = meta.account_id or default_account_id() or ""
    rule = read_rules().get(account)
    state = limit_state(rows, account, rule.at_pct if rule is not None else NO_FALLBACK_LINE_PCT, now)
    if state is not None and state.at_limit:
        _seen_at_limit[session_id] = stop.uuid
    if not should_resume(stop=stop, resumed=meta.limit_resumed, state=state,
                         seen_at_limit=_seen_at_limit.get(session_id) == stop.uuid):
        return False
    if meta.sleep is None and await asyncio.to_thread(claude_pid_in_pane, session_id) is None:
        return False            # nothing runs in the tab: it is not started for this
    with claimed(session_id) as mine:
        if not mine:
            return False
        meta.limit_resumed = stop.uuid           # before sending: a restart in between must not send it twice
        save_sessions_meta()
        sent = await send_to_tab(session_id, resume_envelope(account))
        if not sent:
            meta.limit_resumed = None            # nothing arrived; the next look tries again
            save_sessions_meta()
        logger.info("limit resume: session=%s account=%s stop=%s asleep=%d sent=%s", session_id, account, stop.uuid,
                    meta.sleep is not None, sent)
        return sent


async def tick() -> list[str]:
    """Look over every tab once. → the tabs that were told to carry on."""
    rows = await asyncio.to_thread(read_all_rate_limits_tail)
    now = time.time()
    return [session_id for session_id in list(sessions_meta) if await _look(session_id, rows, now)]


async def resume_loop(interval_sec: float = TICK_SEC) -> None:
    """Look over the tabs every `interval_sec` (= the rollover's interval)."""
    logger.info("resume_loop started (interval=%ds)", interval_sec)
    try:
        while True:
            await asyncio.sleep(interval_sec)
            try:
                await tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("resume_loop iteration failed")
    except asyncio.CancelledError:
        logger.info("resume_loop cancelled")
        raise
