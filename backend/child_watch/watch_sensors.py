"""Reads what the child watch needs about a child tab: its memo, and whether its claude runs and is at a break. Blocking
(files, process table); callers on the event loop run it in a thread.

"At a break" is the account fallback's reading of a tab (`account_fallback.fallback_sensors.read_tab_break`): the sleep
judgement asked by hand, with a usage-limit stop taken into account. A child that answers, runs a command, waits for a
tool, has a wake-up or a cron job scheduled, is on a call or is rolling over is not at a break.

Used by `watch_patrol.py`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import backend.jsonl.jsonl_watcher as jsonl_watcher
from backend._common.state import SessionDef, sessions_meta
from backend.account_fallback.fallback_sensors import read_tab_break
from backend.child_watch.child_memo import memo_state
from backend.child_watch.watch_judgement import is_watched, stop_reason
from backend.sleep.sleep_sensors import record_facts_of
from backend.terminal.tab_memo import memo_file, tier_folder

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChildLook:
    """A watched child found at a break: the time of the last row of its conversation (= which stop it is) and why
    it stopped."""
    mark: float
    reason: str


def _memo_of(meta: SessionDef) -> Path | None:
    """The child's memo: in the tier folder of the child, or of its parent (`tabs new` writes it in the parent's)."""
    for tab_id in (meta.id, meta.parent_id):
        if tab_id in sessions_meta:
            path = memo_file(tier_folder(tab_id), meta.id)
            if path.is_file():
                return path
    return None


def is_watching(meta: SessionDef) -> bool:
    """Whether the tab is one the watch looks at (= `is_watched`, with its memo read). Blocking."""
    return is_watched(child=meta.child, parent_known=meta.parent_id in sessions_meta, asleep=meta.sleep is not None,
                      memo_state=memo_state(_memo_of(meta)) if meta.child else "")


def look_at_child(meta: SessionDef) -> ChildLook | None:
    """The child's look when its claude runs and it is at a break; None when it is not (or its record cannot be
    read). Call it for a tab `is_watching` accepts. Blocking."""
    taken = read_tab_break(meta.id)
    if not taken.at_break:
        return None
    record = jsonl_watcher.get_jsonl_for(meta.id)
    if record is None:
        return None
    try:
        facts = record_facts_of(record)
    except OSError:
        logger.debug("child watch: a record could not be read: %s", record)
        return None
    if facts.last_row_at is None:
        return None
    # TODO: read `RecordFacts.continuation_owed` directly once the record facts carry it
    owed = bool(getattr(facts, "continuation_owed", False))
    return ChildLook(mark=facts.last_row_at, reason=stop_reason(limit_stop=taken.stop is not None,
                                                                  continuation_owed=owed))
