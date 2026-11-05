"""Reads whether a tab is at a break where it may be moved to another account. Blocking (process table, files);
callers on the event loop run it in a thread.

A tab is at a break when the sleep judgement, asked by hand, finds nothing in the way (`sleep_judgement.judge`). A tab
whose turn a usage limit stopped is judged the same way, except for what the stop itself leaves looking like work in
progress (the open turn, the call without a result, the start): what really runs under it still holds it. The record a
sleeping tab keeps is read for the stop too.

Used by `fallback_patrol.py`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import backend.jsonl.jsonl_watcher as jsonl_watcher
from backend._common.state import sessions_meta
from backend.sleep.record_facts import LimitStop
from backend.sleep.sleep_judgement import judge
from backend.sleep.sleep_sensors import gather, record_facts_of

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
    stop = _stop_of(jsonl_watcher.get_jsonl_for(session_id))
    stopped = stop is not None
    facts = gather(session_id, 0, by_hand=True, stopped_by_limit=stopped)
    return TabBreak(stop, judge(facts, 0, by_hand=True, stopped_by_limit=stopped))


def sleeping_stop(session_id: str) -> LimitStop | None:
    """The usage-limit stop the conversation of a sleeping tab ends in."""
    meta = sessions_meta.get(session_id)
    return _stop_of(Path(meta.sleep.record)) if meta is not None and meta.sleep is not None else None
