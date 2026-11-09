"""Reads whether a tab is at a break where it may be moved to another account. Blocking (process table, files);
callers on the event loop run it in a thread.

A tab is at a break when the sleep judgement, asked by hand, finds nothing in the way (`sleep_judgement.judge`). A tab
whose turn a usage limit stopped is judged the same way, except for what the stop itself leaves looking like work in
progress (the open turn, the call without a result, the start): what really runs under it still holds it. The record a
sleeping tab keeps is read for the stop too. The continuation Claude Code booked at a limit is read as well: the move
starts claude again, which loses it, so the patrol sends it in its place. What decides whether the tab's cache is cold
(how long the tab has been quiet, its context and the line where the rollover takes it over) is read with the break,
since the same reading finds it.

Used by `fallback_patrol.py`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import backend.jsonl.jsonl_watcher as jsonl_watcher
from backend._common.state import sessions_meta
from backend.sleep.record_facts import LimitStop, RecordFacts
from backend.sleep.sleep_judgement import judge
from backend.sleep.sleep_sensors import gather, record_facts_of

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TabBreak:
    """What was read about a tab: the usage-limit stop its conversation ends in (None when it does not), the
    conditions that keep the tab from being interrupted (empty = it is at a break), the stop whose continuation is
    still owed (None when there is none; see `RecordFacts.continuation_owed`), and the facts the cold cache is judged
    from (`fallback_judgement.cold_reasons`; None = not read, which a tab that is not at a break leaves)."""
    stop: LimitStop | None
    blocked_by: tuple[str, ...]
    owed: LimitStop | None = None
    quiet_minutes: float | None = None
    context_pct: float | None = None
    rollover_idle_pct: float | None = None

    @property
    def at_break(self) -> bool:
        return not self.blocked_by


def _facts_of(record: Path | None) -> RecordFacts:
    """What the record says; nothing when there is no record or it cannot be read."""
    if record is None:
        return RecordFacts()
    try:
        return record_facts_of(record)
    except OSError:
        logger.debug("account fallback: a record could not be read: %s", record)
        return RecordFacts()


def read_tab_break(session_id: str) -> TabBreak:
    """Read the stop, the owed continuation, the break and the cache facts of a running tab."""
    record = _facts_of(jsonl_watcher.get_jsonl_for(session_id))
    stopped = record.limit_stop is not None
    facts = gather(session_id, 0, by_hand=True, stopped_by_limit=stopped)
    return TabBreak(record.limit_stop, judge(facts, 0, by_hand=True, stopped_by_limit=stopped),
                    owed=record.continuation_owed, quiet_minutes=facts.quiet_minutes, context_pct=facts.context_pct,
                    rollover_idle_pct=facts.rollover_idle_pct)


def sleeping_stop(session_id: str) -> LimitStop | None:
    """The usage-limit stop the conversation of a sleeping tab ends in."""
    meta = sessions_meta.get(session_id)
    if meta is None or meta.sleep is None:
        return None
    return _facts_of(Path(meta.sleep.record)).limit_stop
