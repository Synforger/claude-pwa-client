"""What the client knows of a tab's permission windows, and what the screen is told (`agent_status.pending_permission`).

The screen decides whether a window is open (`note_screen`: the detector's looks, read by `window_screen.py`) and the
record decides what it is (the oldest call without a result: `window_table.py`). A `PermissionRequest` hook carries the
tool's whole input and is no evidence of a window: it is kept as the input the window shows. A window the screen shows
that no hook came for is shown from the record's call, and is not answered by a key.

A window is answered by a key only when the screen has shown it since the last answer, the window offers `Yes` and `No`
and nothing else, and the command of the hook's input is on the screen whole (`answerable`). The input box on two looks in
a row ends the windows the client remembers (= `input_looks`, which also says when kept messages are typed).

The table of the record's calls is read again from the record's turn when the backend has not seen its rows (a restart): in a
thread, by the callers that wait (`prepare`), never by the one that folds a row. A question or a plan the record does not
hold yet (Claude Code writes them after the answer) is known from its hook until the screen shows the input box again.

Used by `routes/hooks.py`, `routes/permission_window.py`, `jsonl/session_status.py`, `terminal/` (the detector and the
send), `sleep/`, `rollover/`, `child_watch/`, `window_hold.py` and `window_answer.py`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import backend.jsonl.jsonl_watcher as jsonl_watcher
from backend._common.state import agent_status, sessions_overview, stream_states
from backend.permission_window import window_table
from backend.permission_window.window_judgement import INPUT_LOOKS_TO_RELEASE, Kind, Situation
from backend.permission_window.window_screen import ScreenKind, ScreenReading, is_yes_no, shows_command
from backend.permission_window.window_table import PLAN_TOOL, QUESTION_TOOL, CallTable

logger = logging.getLogger(__name__)

# How long a window may stay open before the parent of a child that waits at it is told (= `child_watch`).
PERMISSION_WAIT_SEC = 300
# How much of the record's end is read at a time when a turn's rows are read again.
_TAIL_CHUNK = 1 << 18


@dataclass
class Window:
    """One window: the input the hook gave (or the record's, when no hook came), and the call of the record it is."""
    number: int
    tool_name: str
    tool_input: dict
    prompt_id: str | None
    opened_at: float
    tool_use_id: str | None = None
    record_input: dict | None = None
    from_hook: bool = True
    pushed: bool = False


@dataclass
class _TabWindows:
    table: CallTable = field(default_factory=CallTable)
    table_read: bool = False
    windows: list[Window] = field(default_factory=list)
    taken: set[str] = field(default_factory=set)
    answered: set[str] = field(default_factory=set)
    next_number: int = 1
    answered_in_batch: int = 0
    reading: ScreenReading | None = None
    input_looks: int = 0
    window_shown: bool = False
    answered_print: str | None = None
    choice_hook: str | None = None
    turn_count: int = 0


_tabs: dict[str, _TabWindows] = {}
_table_lock = threading.Lock()


def _tab(session_id: str) -> _TabWindows:
    return _tabs.setdefault(session_id, _TabWindows())


def _waiting(tab: _TabWindows) -> dict[str, window_table.RecordedCall]:
    """The record's calls without a result that are not answered yet (= one a key was typed for is running, or about to
    be refused, and is no window)."""
    return {tool_use_id: call for tool_use_id, call in tab.table.open.items() if tool_use_id not in tab.answered}


def _ordered(tab: _TabWindows) -> list[Window]:
    """The tab's windows in the order the record's calls were made, a window not tied to a call last."""
    order = {tool_use_id: index for index, tool_use_id in enumerate(tab.table.open)}
    return sorted(tab.windows, key=lambda window: (order.get(window.tool_use_id, len(order)), window.number))


def kind_of(session_id: str) -> Kind:
    """What the window of the tab is by its record: the oldest call without a result."""
    tab = _tab(session_id)
    _read_table(session_id, tab)
    kind = window_table.oldest_kind(_waiting(tab))
    if kind is Kind.NONE and tab.choice_hook is not None:
        return Kind.QUESTION if tab.choice_hook == QUESTION_TOOL else Kind.PLAN
    return kind


def is_open(session_id: str) -> bool:
    """Whether the tab waits at a permission window now (= the `PERMISSION_OPEN` of the judgements): the last look
    showed a window and the record's oldest call without a result is an approval."""
    tab = _tabs.get(session_id)
    return tab is not None and _permission_on_screen(tab)


def _permission_on_screen(tab: _TabWindows) -> bool:
    return (tab.reading is not None and tab.reading.kind is ScreenKind.WINDOW
            and window_table.oldest_kind(_waiting(tab)) is Kind.APPROVAL)


def permission_opened_at(session_id: str) -> float | None:
    """When the oldest window of the tab that waits at a permission window was opened, None when it does not."""
    tab = _tabs.get(session_id)
    if tab is None or not _permission_on_screen(tab) or not tab.windows:
        return None
    return min(window.opened_at for window in tab.windows)


def input_looks(session_id: str) -> int:
    """How many looks in a row showed the input box."""
    tab = _tabs.get(session_id)
    return 0 if tab is None else tab.input_looks


def current_window(session_id: str) -> Window | None:
    """The window the pane shows now (= the oldest the client knows of). None when it knows none."""
    tab = _tabs.get(session_id)
    ordered = _ordered(tab) if tab is not None else []
    return ordered[0] if ordered else None


def situation(session_id: str, reading: ScreenReading, *, backlog: bool = False) -> Situation:
    """What the judgement reads for a look at the pane (`reading`) just taken: the record's kind and, for a window, whether
    a key may answer it."""
    tab = _tab(session_id)
    kind = kind_of(session_id)
    window = current_window(session_id)
    return Situation(reading.kind, kind, answerable=_answerable(tab, window, reading, kind),
                     input_looks=tab.input_looks, backlog=backlog)


def _answerable(tab: _TabWindows, window: Window | None, reading: ScreenReading, kind: Kind) -> bool:
    if window is None or not window.from_hook or kind is not Kind.APPROVAL or reading.kind is not ScreenKind.WINDOW:
        return False
    command, description = window.tool_input.get("command"), window.tool_input.get("description")
    return (tab.window_shown and is_yes_no(reading) and isinstance(command, str)
            and shows_command(reading, command, description if isinstance(description, str) else None))


def _view(session_id: str) -> dict | None:
    """What the screen is told (= the contract's `pending_permission`)."""
    tab = _tabs.get(session_id)
    window = current_window(session_id)
    if tab is None or window is None or not _permission_on_screen(tab):
        return None
    return {"number": window.number, "tool_use_id": window.tool_use_id, "tool_name": window.tool_name,
            "input": window.tool_input, "record_input": window.record_input,
            "answerable": _answerable(tab, window, tab.reading, Kind.APPROVAL),
            "index": tab.answered_in_batch + 1, "count": tab.answered_in_batch + len(tab.windows),
            "opened_at": window.opened_at}


def _publish(session_id: str) -> None:
    """Put the tab's window into `agent_status` and wake the screens when what they show changed."""
    status = agent_status.get(session_id)
    if status is None:
        return
    view = _view(session_id)
    if status.get("pending_permission") == view:
        return
    status["pending_permission"] = view
    state = stream_states.get(session_id)
    if state is not None:
        state.status_event.set()
    sessions_overview.notify()


def _tie(tab: _TabWindows, window: Window, calls: dict[str, window_table.RecordedCall]) -> bool:
    """Tie the window to the call of `calls` it asks about. True when it was tied."""
    call = window_table.select(calls, window.tool_name, window.tool_input, frozenset(tab.taken))
    if call is None:
        return False
    window.tool_use_id = call.tool_use_id
    window.record_input = call.tool_input if call.tool_input != window.tool_input else None
    tab.taken.add(call.tool_use_id)
    return True


def open_window(session_id: str, tool_name: str, tool_input: dict, prompt_id: str | None = None, *,
                now: float | None = None) -> Window | None:
    """Keep the input a `PermissionRequest` hook gave. None when the record already holds the result of the call (= a guard
    answered before the hook arrived: no window was ever shown). A window the screen showed before the hook came is
    taken over: the hook's input is the one it shows from now on."""
    tab = _tab(session_id)
    if window_table.select(tab.table.resolved, tool_name, tool_input, frozenset(tab.taken)) is not None \
            and window_table.select(tab.table.open, tool_name, tool_input, frozenset(tab.taken)) is None:
        logger.info("permission window: not kept, the record has its result session=%s tool=%s", session_id, tool_name)
        return None
    window = _from_screen_alone(tab, tool_name, tool_input)
    if window is None:
        window = Window(number=tab.next_number, tool_name=tool_name, tool_input=tool_input, prompt_id=prompt_id,
                        opened_at=time.time() if now is None else now)
        tab.next_number += 1
        _tie(tab, window, tab.table.open)
        tab.windows.append(window)
    else:
        window.tool_input, window.prompt_id, window.from_hook = tool_input, prompt_id, True
        call = tab.table.open.get(window.tool_use_id or "")
        window.record_input = call.tool_input if call is not None and call.tool_input != tool_input else None
    logger.info("permission window: hook input kept session=%s number=%d tool=%s tied=%s", session_id, window.number,
                tool_name, window.tool_use_id is not None)
    _publish(session_id)
    return window


def _from_screen_alone(tab: _TabWindows, tool_name: str, tool_input: dict) -> Window | None:
    """The window of the same call that the screen showed with no hook (= it shows the record's input), if any."""
    call = window_table.select(tab.table.open, tool_name, tool_input, frozenset())
    for window in tab.windows:
        if not window.from_hook and call is not None and window.tool_use_id == call.tool_use_id:
            return window
    return None


def fold_row(session_id: str, row: dict) -> None:
    """Take a row of the tab's conversation record in: the table of calls grows or shrinks, a window not yet tied to its
    call is tied once the call is written, and a window whose call has its result goes."""
    tab = _tab(session_id)
    effect = window_table.effect_of_row(row)
    with _table_lock:
        window_table.apply_effect(tab.table, effect)
        tab.turn_count += effect.new_turn
    if any(call.tool_name in (QUESTION_TOOL, PLAN_TOOL) for call in effect.added) or effect.new_turn:
        tab.choice_hook = None      # the record has the call now, or the turn that asked it is over
    for call in effect.added:
        for window in _ordered(tab):
            if window.tool_use_id is None and _tie(tab, window, {call.tool_use_id: call}):
                break
    tab.answered.difference_update(effect.resolved_ids)
    for window in [window for window in tab.windows if window.tool_use_id in effect.resolved_ids]:
        tab.windows.remove(window)
        logger.info("permission window: gone, the record has its result session=%s number=%d tool=%s", session_id,
                    window.number, window.tool_name)
    if effect.new_turn:
        tab.windows.clear()
        tab.taken.clear()
        tab.answered.clear()
    if effect.added or effect.resolved_ids or effect.new_turn:
        _publish(session_id)


async def prepare(session_id: str) -> None:
    """Read the table of the record's turn, in a thread, if the backend has not seen the rows of it: the callers that wait
    (the detector's look at a window, the hook) call this before they take the screen or the hook in."""
    tab = _tab(session_id)
    if tab.table_read:
        return
    await asyncio.to_thread(_read_table, session_id, tab)
    _refresh_windows(session_id, tab)


async def look(session_id: str, reading: ScreenReading) -> None:
    """The detector's look at the pane: `note_screen`, after the table is read when the screen shows a window."""
    if reading.kind is ScreenKind.WINDOW:
        await prepare(session_id)
    note_screen(session_id, reading)


def note_screen(session_id: str, reading: ScreenReading) -> None:
    """The detector looked at the pane. The input box on `INPUT_LOOKS_TO_RELEASE` looks in a row ends the windows the client
    remembers; a window on the screen is shown to the screen (and, when no hook came for it, from the record's call)."""
    tab = _tab(session_id)
    tab.reading = reading
    tab.input_looks = tab.input_looks + 1 if reading.kind is ScreenKind.INPUT else 0
    if tab.input_looks >= INPUT_LOOKS_TO_RELEASE:
        tab.choice_hook = None
        if tab.windows or tab.answered_in_batch:
            tab.windows.clear()
            tab.taken.clear()
            tab.answered_in_batch = 0
            logger.info("permission window: forgotten, the input box is on the screen session=%s", session_id)
    if reading.kind is ScreenKind.WINDOW:
        tab.window_shown = tab.window_shown or reading.fingerprint != tab.answered_print
        _stand_up_from_record(session_id, tab)
    else:
        tab.window_shown = False
        tab.answered_print = None
    _publish(session_id)


def forget_screen(session_id: str) -> None:
    """The tab has no pane (or no claude) to look at: what the last look showed is gone with it."""
    tab = _tabs.get(session_id)
    if tab is None or tab.reading is None and not tab.windows:
        return
    tab.reading = None
    tab.input_looks = 0
    tab.window_shown = False
    tab.answered_print = None
    tab.windows.clear()
    tab.taken.clear()
    tab.answered_in_batch = 0
    tab.choice_hook = None
    _publish(session_id)


def take_unpushed(session_id: str) -> Window | None:
    """The permission window the screen shows that has not been pushed yet (one push per window, when the screen first shows
    it), marked as pushed. None when there is none."""
    tab = _tabs.get(session_id)
    window = current_window(session_id)
    if tab is None or window is None or window.pushed or not _permission_on_screen(tab):
        return None
    window.pushed = True
    return window


def note_choice_hook(session_id: str, tool_name: str) -> None:
    """A question or a plan asked through its hook: until the record holds the call (Claude Code writes it after the answer)
    or the screen shows the input box again, the window is that question or that plan."""
    _tab(session_id).choice_hook = tool_name


def _stand_up_from_record(session_id: str, tab: _TabWindows) -> None:
    """A window the screen shows, an approval by the record, and no window known for the oldest call: stand one up from the
    record's call (no hook came, or it was missed: it is shown, and not answered by a key)."""
    waiting = _waiting(tab)
    if not tab.window_shown or window_table.oldest_kind(waiting) is not Kind.APPROVAL:
        return
    call = next(iter(waiting.values()))
    if any(window.tool_use_id == call.tool_use_id for window in tab.windows):
        return
    window = Window(number=tab.next_number, tool_name=call.tool_name, tool_input=call.tool_input, prompt_id=None,
                    opened_at=time.time(), tool_use_id=call.tool_use_id, from_hook=False)
    tab.next_number += 1
    tab.taken.add(call.tool_use_id)
    tab.windows.append(window)
    logger.info("permission window: shown from the record, no hook session=%s number=%d tool=%s", session_id, window.number,
                call.tool_name)


def mark_answer_typed(session_id: str, fingerprint: str) -> None:
    """Called inside the typing lock, with the key: another answer that comes after it finds the window not shown since the
    last answer. Two attributes only, so that it is safe in the typing thread; `note_answered` does the rest."""
    tab = _tab(session_id)
    tab.window_shown = False
    tab.answered_print = fingerprint


def note_answered(session_id: str, number: int, fingerprint: str) -> None:
    """A key was typed for the window `number` while the screen showed `fingerprint`: the window goes, and the next one is
    answered only once the screen has shown another."""
    tab = _tab(session_id)
    for window in tab.windows:
        if window.number == number:
            tab.windows.remove(window)
            tab.answered_in_batch += 1
            if window.tool_use_id is not None:
                tab.answered.add(window.tool_use_id)
            break
    tab.window_shown = False
    tab.answered_print = fingerprint
    _publish(session_id)


def close_all(session_id: str, reason: str) -> None:
    """Forget every window of the tab, the calls of its turn and what the last look showed: it restarted, started a
    conversation or ended its turn."""
    tab = _tabs.get(session_id)
    if tab is None:
        return
    had_windows = bool(tab.windows)
    with _table_lock:
        tab.table.clear()
        tab.table_read = True
    tab.windows.clear()
    tab.taken.clear()
    tab.answered.clear()
    tab.answered_in_batch = 0
    tab.window_shown = False
    tab.answered_print = None
    tab.reading = None
    tab.input_looks = 0
    tab.choice_hook = None
    if had_windows:
        logger.info("permission window: closed all session=%s reason=%s", session_id, reason)
    _publish(session_id)


def _read_table(session_id: str, tab: _TabWindows) -> None:
    """Read the table again from the record's turn, once, when the backend has not seen the rows of the turn (= it
    started after them). Blocks on the record's end, so it is called in a thread (`prepare`) or by one (the typing). The rows
    folded since the backend started are kept (a row written after the read is not in it); a new turn that began meanwhile
    makes the rows read the turn before, and they are not used."""
    if tab.table_read:
        return
    with _table_lock:
        if tab.table_read:
            return
        turn = tab.turn_count
    path = jsonl_watcher.get_jsonl_for(session_id)
    try:
        rows = _rows_of_turn(path) if path is not None else []
    except OSError:
        logger.warning("permission window: the record could not be read session=%s", session_id, exc_info=True)
        rows = []
    with _table_lock:
        if tab.table_read:
            return
        if tab.turn_count == turn:
            read = window_table.table_of_turn(rows)
            for tool_use_id, call in tab.table.open.items():
                if tool_use_id not in read.resolved:
                    read.open.setdefault(tool_use_id, call)
            for tool_use_id, call in tab.table.resolved.items():
                read.open.pop(tool_use_id, None)
                read.resolved.setdefault(tool_use_id, call)
            tab.table = read
        tab.table_read = True


def _refresh_windows(session_id: str, tab: _TabWindows) -> None:
    """After the table was read: tie the windows that had no call yet, drop those whose call has its result."""
    for window in _ordered(tab):
        if window.tool_use_id is None:
            _tie(tab, window, tab.table.open)
    for window in [window for window in tab.windows if window.tool_use_id in tab.table.resolved]:
        tab.windows.remove(window)
    _publish(session_id)


def _rows_of_turn(path: Path) -> list[dict]:
    """The rows of the turn the record ends in, oldest first: read from the end, up to the row that began the turn."""
    rows: list[dict] = []
    with path.open("rb") as handle:
        handle.seek(0, 2)
        position, rest = handle.tell(), b""
        while position > 0:
            step = min(_TAIL_CHUNK, position)
            position -= step
            handle.seek(position)
            lines = (handle.read(step) + rest).split(b"\n")
            rest = lines[0]
            for line in reversed(lines[1:]):
                row = _parse(line)
                if row is None:
                    continue
                rows.append(row)
                if window_table.effect_of_row(row).new_turn:
                    return rows[::-1]
        row = _parse(rest)
        if row is not None:
            rows.append(row)
    return rows[::-1]


def _parse(line: bytes) -> dict | None:
    if not line.strip():
        return None
    try:
        row = json.loads(line)
    except ValueError:
        return None
    return row if isinstance(row, dict) else None
