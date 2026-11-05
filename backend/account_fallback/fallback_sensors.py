"""Reads whether a tab is at a break where it may be moved to another account. Blocking (process table, files);
callers on the event loop run it in a thread.

A tab is at a break when the sleep judgement, asked by hand, finds nothing in the way (`sleep_judgement.judge`); a tab
whose turn a usage limit stopped is at a break by that very stop, except that a voice call or an automatic rollover in
progress still holds it. The record a sleeping tab keeps is read for the stop too.

Used by `fallback_patrol.py`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import backend.jsonl.jsonl_watcher as jsonl_watcher
import backend.rollover.rollover as rollover
from backend._common.state import is_session_on_call, sessions_meta
from backend.sleep.record_facts import LimitStop
from backend.sleep.sleep_judgement import SleepFacts, judge
from backend.sleep.sleep_sensors import gather, record_facts_of
from backend.terminal.pty_discover import claude_pid_in_pane

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TabBreak:
    """What was read about a tab: the usage-limit stop its conversation ends in (None when it does not), and the
    conditions that keep the tab from being interrupted (empty = it is at a break)."""
    stop: LimitStop | None
    blocked_by: tuple[str, ...]

    @property
    def at_break(self) -> bool:
        return not self.blocked_by


def _stop_of(record: Path | None) -> LimitStop | None:
    if record is None:
        return None
    try:
        return record_facts_of(record).limit_stop
    except OSError:
        logger.debug("account fallback: a record could not be read: %s", record)
        return None


def read_tab_break(session_id: str) -> TabBreak:
    """Read the stop and the break of a running tab."""
    record = jsonl_watcher.get_jsonl_for(session_id)
    stop = _stop_of(record)
    if stop is None:
        return TabBreak(None, judge(gather(session_id, 0, by_hand=True), 0, by_hand=True))
    held = SleepFacts(claude_running=claude_pid_in_pane(session_id) is not None,
                      on_voice_call=is_session_on_call(session_id),
                      rolling_over=rollover.asked(record) if record is not None else False)
    return TabBreak(stop, judge(held, 0, by_hand=True))


def sleeping_stop(session_id: str) -> LimitStop | None:
    """The usage-limit stop the conversation of a sleeping tab ends in."""
    meta = sessions_meta.get(session_id)
    return _stop_of(Path(meta.sleep.record)) if meta is not None and meta.sleep is not None else None
