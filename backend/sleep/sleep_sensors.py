"""Reads what the sleep judgement needs about a tab: its claude's process, the state of its turn, its conversation
record and the processes under it. Blocking (process table, files); callers on the event loop run it in a thread.

The facts are read cheapest first and the reading stops at the first condition that fails (`sleep_judgement.judge`),
so a tab that is plainly not ready costs a process lookup and nothing more.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import time
from pathlib import Path

import psutil

import backend.jsonl.jsonl_watcher as jsonl_watcher
import backend.rollover.rollover as rollover
from backend._common.state import is_session_on_call, sessions_meta, stream_states
from backend.routes.overview import context_pct_of, is_busy
from backend.sleep.record_facts import RecordFacts, fold_row
from backend.sleep.sleep_judgement import ProcessNode, SleepFacts, foreign_processes, judge
from backend.sleep.sleep_settings import rollover_idle_pct
from backend.terminal import input_ready
from backend.terminal.pty_discover import claude_pid_in_pane

logger = logging.getLogger(__name__)

# A record is read in pieces of this size, so that a record of hundreds of megabytes never sits in memory whole.
READ_CHUNK_BYTES = 4 * 1024 * 1024
# How deep under a claude the processes are looked at, and how many in all (= a runaway tree never stalls the patrol).
PROCESS_DEPTH_MAX = 8
PROCESS_COUNT_MAX = 300
# Arguments of a process that can name the tool it runs (= `node /path/typescript-language-server --stdio`).
NAMED_ARGUMENTS = 3

# When each tab last woke or had a conversation opened in it (unix seconds). The quiet time is measured from the latest
# of this, the start of the claude now running in the tab, and the newest row of its conversation: a tab that just
# woke, or whose operator just reopened an old conversation (= `/resume` inside a running claude), has done nothing
# yet, and measured by its old rows it would sleep again within a minute. This is kept in memory; the claude's start
# is the part that outlives a restart of the backend.
_woken_at: dict[str, float] = {}


def note_woken(session_id: str, at: float | None = None) -> None:
    """Record that the tab woke, or had a conversation opened in it, now (or at `at`): its quiet time starts over."""
    _woken_at[session_id] = time.time() if at is None else at


def claude_started_at(pid: int) -> float:
    """When the claude `pid` started (unix seconds), 0 when it cannot be read."""
    try:
        return psutil.Process(pid).create_time()
    except (psutil.Error, OSError):
        return 0.0


# Per record: how far it was read and what the rows read so far left behind. Only a shortcut: a record read from
# its start again gives the same facts, so a restart of the backend loses nothing.
_scans: dict[str, tuple[int, RecordFacts]] = {}


def record_facts_of(record: Path) -> RecordFacts:
    """The facts of a whole conversation record, reading only what was written since the last call."""
    key = str(record)
    offset, facts = _scans.get(key, (0, RecordFacts()))
    if record.stat().st_size < offset:
        offset, facts = 0, RecordFacts()
    read_bytes, carry = 0, b""
    with record.open("rb") as fh:
        fh.seek(offset)
        while chunk := fh.read(READ_CHUNK_BYTES):
            read_bytes += len(chunk)
            data = carry + chunk
            cut = data.rfind(b"\n") + 1          # a last line without a newline is still being written
            for raw in data[:cut].split(b"\n"):
                _fold_line(facts, raw)
            carry = data[cut:]
    _scans[key] = (offset + read_bytes - len(carry), facts)
    return dataclasses.replace(facts)


def _fold_line(facts: RecordFacts, raw: bytes) -> None:
    if not raw.strip():
        return
    try:
        fold_row(facts, json.loads(raw))
    except ValueError:
        logger.debug("sleep: a line of a record could not be parsed")


def last_activity(record: Path, scanned: RecordFacts) -> float:
    """When the conversation last did anything (unix seconds): the newest row time of the record (`scanned`, its
    facts) and of the records of its sub-agents (= the `subagents/` folder named like the record, next to it). A
    record with no row time counts by its modification time."""
    newest = _activity_of(record, scanned)
    for path in record.with_suffix("").joinpath("subagents").rglob("*.jsonl"):
        try:
            newest = max(newest, _activity_of(path, record_facts_of(path)))
        except OSError:
            continue
    return newest


def _activity_of(record: Path, scanned: RecordFacts) -> float:
    return scanned.last_row_at if scanned.last_row_at is not None else record.stat().st_mtime


def _names_of(process: psutil.Process) -> tuple[str, ...]:
    """The names a process goes by: its own, and the base names of its first arguments."""
    names: list[str] = []
    try:
        names.append(Path(process.name()).name)
        names.extend(Path(arg).name for arg in process.cmdline()[:NAMED_ARGUMENTS] if arg and not arg.startswith("-"))
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        # benign: a process that ended or cannot be read keeps the names read so far; none at all reads as `?` (= work)
        pass
    return tuple(dict.fromkeys(name for name in names if name))


def process_tree(pid: int) -> tuple[ProcessNode, ...]:
    """The processes under `pid`, as a tree. A process that cannot be read has the name `?` (= it counts as work)."""
    budget = [PROCESS_COUNT_MAX]

    def below(parent: psutil.Process, depth: int) -> tuple[ProcessNode, ...]:
        if depth >= PROCESS_DEPTH_MAX:
            return ()
        try:
            children = parent.children()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return ()
        nodes = []
        for child in children:
            if budget[0] <= 0:
                break
            budget[0] -= 1
            nodes.append(ProcessNode(names=_names_of(child) or ("?",), children=below(child, depth + 1)))
        return tuple(nodes)

    try:
        return below(psutil.Process(pid), 0)
    except psutil.NoSuchProcess:
        return ()


def _turn_open(session_id: str) -> bool:
    """Whether claude is answering or a message waits in its queue. This is what the hooks tell (= the last one is not
    a `Stop`, or a `UserPromptSubmit` came after it), read from the state they and the record leave: the busy flag
    that a `Stop` ends and a `UserPromptSubmit` sets again, and the count of messages queued behind a turn."""
    state = stream_states.get(session_id)
    return is_busy(session_id) or (state is not None and state.queued_sends > 0)


def _account_pending(session_id: str) -> bool:
    """Whether the account fallback or hold asked the tab for a break or owes it a "carry on" (= the tab is theirs)."""
    meta = sessions_meta.get(session_id)
    return meta is not None and (meta.owes_carry_on or meta.pause_asked_at is not None or meta.hold_asked_at is not None)


def gather(session_id: str, minutes: int, by_hand: bool = False, stopped_by_limit: bool = False,
           reported: bool = False) -> SleepFacts:
    """Read the facts about a tab, cheapest first, and stop at the first condition that fails. `minutes` is how long
    the tab must have been quiet; `by_hand` reads for a sleep its parent asked for, `stopped_by_limit` for a tab
    whose turn a usage limit stopped and `reported` for a child that reported its work done (= `judge`), so the facts
    those leave out are read past."""
    pid = claude_pid_in_pane(session_id)
    facts = SleepFacts(claude_running=pid is not None)
    if pid is None:
        return facts
    facts = dataclasses.replace(facts, starting=not input_ready.is_ready(session_id), turn_open=_turn_open(session_id),
                                on_voice_call=is_session_on_call(session_id),
                                account_pending=_account_pending(session_id))
    if judge(facts, minutes, by_hand, stopped_by_limit, reported):
        return facts
    record = jsonl_watcher.get_jsonl_for(session_id)
    try:
        scanned = record_facts_of(record) if record is not None else None
        activity = last_activity(record, scanned) if record is not None and scanned else None
        started = max(_woken_at.get(session_id, 0.0), claude_started_at(pid))
        since = max(activity, started) if activity is not None else None
        quiet = (time.time() - since) / 60 if since is not None else None
    except OSError:
        scanned, activity, started, quiet = None, None, 0.0, None
    facts = dataclasses.replace(facts, record_found=quiet is not None, quiet_minutes=quiet,
                                answered_since_start=activity > started if activity is not None else None)
    if judge(facts, minutes, by_hand, stopped_by_limit, reported) or record is None:
        return facts
    facts = dataclasses.replace(facts, context_pct=context_pct_of(session_id),
                                rollover_idle_pct=rollover_idle_pct(session_id),
                                rolling_over=rollover.asked(record))
    if judge(facts, minutes, by_hand, stopped_by_limit, reported):
        return facts
    facts = dataclasses.replace(facts, record=scanned)
    if judge(facts, minutes, by_hand, stopped_by_limit, reported):
        return facts
    return dataclasses.replace(facts, foreign_processes=foreign_processes(process_tree(pid)))
