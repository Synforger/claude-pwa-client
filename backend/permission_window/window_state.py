"""The windows a tab's Claude Code has open, and what the screen is told about them (`agent_status.pending_permission`).

A window is stood up by a `PermissionRequest` hook (`open_window`), tied to the tool call of the conversation record it
asks about (`window_table.py`; the rows come through `fold_row`) and watched on the pane: the detector tells on each look
whether a selection prompt is on the screen (`note_screen`), and a window that was seen and is then missing on two looks in
a row is closed. A call's result row, a key typed for the answer, a restart, a new conversation and the end of the turn
close windows too. `AskUserQuestion` and `ExitPlanMode` ask through the same hook but have a screen of their own: they are
kept as windows without being shown (`is_open` says no, `is_holding` says yes), so that what is typed to the tab waits for
them as it waits for a permission window.

Windows ask one at a time in the order of the record's calls: the one the pane shows is always the oldest.

Used by `routes/hooks.py`, `routes/permission_window.py`, `jsonl/session_status.py`, `terminal/` (the detector, the send
and the receipt), `sleep/`, `rollover/`, `child_watch/`, `window_hold.py` and `window_answer.py`.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from backend._common.state import agent_status, sessions_overview, stream_states
from backend.permission_window import window_table
from backend.permission_window.window_table import CallTable

logger = logging.getLogger(__name__)

# The tools whose window is the screen's own (a plan to approve, a question to answer): kept, never shown as a permission.
CHOICE_TOOLS = frozenset({"AskUserQuestion", "ExitPlanMode"})
# How many looks in a row a window that was seen must be missing from the pane to be closed.
SCREEN_MISSES_TO_CLOSE = 2
# How long a window may stay open before the parent of a child that waits at it is told (= `child_watch`).
PERMISSION_WAIT_SEC = 300


@dataclass
class Window:
    """One window: what the hook said, the call of the record it belongs to, and whether the pane showed it."""
    number: int
    tool_name: str
    tool_input: dict
    prompt_id: str | None
    opened_at: float
    tool_use_id: str | None = None
    record_input: dict | None = None
    seen: bool = False
    misses: int = 0

    @property
    def is_permission(self) -> bool:
        return self.tool_name not in CHOICE_TOOLS


@dataclass
class _TabWindows:
    table: CallTable = field(default_factory=CallTable)
    windows: list[Window] = field(default_factory=list)
    taken: set[str] = field(default_factory=set)
    next_number: int = 1
    answered_in_batch: int = 0


_tabs: dict[str, _TabWindows] = {}
_close_listeners: list[Callable[[str], None]] = []


def add_close_listener(listener: Callable[[str], None]) -> None:
    """Call `listener(session_id)` whenever a window of a tab closes (= the tab may have nothing open now)."""
    if listener not in _close_listeners:
        _close_listeners.append(listener)


def _tab(session_id: str) -> _TabWindows:
    return _tabs.setdefault(session_id, _TabWindows())


def _ordered(tab: _TabWindows) -> list[Window]:
    """The tab's windows in the order the pane asks them: by the record's call order, a window not yet tied last."""
    order = {tool_use_id: index for index, tool_use_id in enumerate(tab.table.open)}
    return sorted(tab.windows, key=lambda window: (order.get(window.tool_use_id, len(order)), window.number))


def current_window(session_id: str) -> Window | None:
    """The window the pane shows now (= the oldest), of any kind. None when none is open."""
    tab = _tabs.get(session_id)
    ordered = _ordered(tab) if tab is not None else []
    return ordered[0] if ordered else None


def current_permission(session_id: str) -> Window | None:
    """The permission window the pane shows now, None when the pane shows none (= another kind of window, or none)."""
    window = current_window(session_id)
    return window if window is not None and window.is_permission else None


def is_open(session_id: str) -> bool:
    """Whether the tab waits at a permission window (= the `PERMISSION_OPEN` of the judgements)."""
    tab = _tabs.get(session_id)
    return tab is not None and any(window.is_permission for window in tab.windows)


def is_holding(session_id: str) -> bool:
    """Whether what is typed to the tab must wait: a permission window, a question or a plan approval is open."""
    tab = _tabs.get(session_id)
    if tab is not None and tab.windows:
        return True
    plan = (agent_status.get(session_id) or {}).get("pending_plan")
    return bool(plan)


def permission_opened_at(session_id: str) -> float | None:
    """When the oldest open permission window of the tab was opened, None when none is open."""
    tab = _tabs.get(session_id)
    opened = [window.opened_at for window in tab.windows if window.is_permission] if tab is not None else []
    return min(opened) if opened else None


def _view(session_id: str) -> dict | None:
    """What the screen is told (= the contract's `pending_permission`)."""
    tab = _tabs.get(session_id)
    window = current_permission(session_id)
    if tab is None or window is None:
        return None
    waiting = sum(1 for each in tab.windows if each.is_permission)
    return {"number": window.number, "tool_use_id": window.tool_use_id, "tool_name": window.tool_name,
            "input": window.tool_input, "record_input": window.record_input,
            "index": tab.answered_in_batch + 1, "count": tab.answered_in_batch + waiting,
            "opened_at": window.opened_at}


def _publish(session_id: str) -> None:
    """Put the tab's windows into `agent_status` and wake the screens when what they show changed."""
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
    """Stand up the window a `PermissionRequest` hook asked for. None when the record already holds the result of the
    call (= a guard answered before the hook arrived: no window was ever shown)."""
    tab = _tab(session_id)
    if window_table.select(tab.table.resolved, tool_name, tool_input, frozenset(tab.taken)) is not None \
            and window_table.select(tab.table.open, tool_name, tool_input, frozenset(tab.taken)) is None:
        logger.info("permission window: not opened, the record has its result session=%s tool=%s", session_id, tool_name)
        return None
    window = Window(number=tab.next_number, tool_name=tool_name, tool_input=tool_input, prompt_id=prompt_id,
                    opened_at=time.time() if now is None else now)
    tab.next_number += 1
    _tie(tab, window, tab.table.open)
    tab.windows.append(window)
    logger.info("permission window: opened session=%s number=%d tool=%s tied=%s", session_id, window.number, tool_name,
                window.tool_use_id is not None)
    _publish(session_id)
    return window


def fold_row(session_id: str, row: dict) -> None:
    """Take a row of the tab's conversation record in: the table of calls grows or shrinks, a window not yet tied to its
    call is tied once the call is written, and a window whose call has its result is closed."""
    tab = _tab(session_id)
    effect = window_table.effect_of_row(row)
    window_table.apply_effect(tab.table, effect)
    for call in effect.added:
        for window in _ordered(tab):
            if window.tool_use_id is None and _tie(tab, window, {call.tool_use_id: call}):
                break
    closed = [window for window in tab.windows if window.tool_use_id in effect.resolved_ids]
    for window in closed:
        _close(session_id, tab, window, "result")
    if effect.added or effect.new_turn:
        _publish(session_id)


def note_screen(session_id: str, selection_prompt_visible: bool) -> None:
    """The detector looked at the pane: the window it shows is the oldest. A window seen once and missing on
    `SCREEN_MISSES_TO_CLOSE` looks in a row is closed."""
    window = current_window(session_id)
    if window is None:
        return
    if selection_prompt_visible:
        if not window.seen:
            window.seen = True
            logger.info("permission window: seen on the pane session=%s number=%d", session_id, window.number)
        window.misses = 0
    elif window.seen:
        window.misses += 1
        if window.misses >= SCREEN_MISSES_TO_CLOSE:
            _close(session_id, _tab(session_id), window, "screen")


def note_answered(session_id: str, number: int) -> None:
    """A key was typed for the window `number`: it is closed, and the next window of the batch is the next one asked."""
    tab = _tab(session_id)
    for window in tab.windows:
        if window.number == number:
            if window.is_permission:
                tab.answered_in_batch += 1
            _close(session_id, tab, window, "answered")
            return


def close_all(session_id: str, reason: str) -> None:
    """Forget every window of the tab and the calls of its turn: it restarted, started a conversation or ended its turn."""
    tab = _tabs.get(session_id)
    if tab is None:
        return
    had_windows = bool(tab.windows)
    tab.windows.clear()
    tab.table.clear()
    tab.taken.clear()
    tab.answered_in_batch = 0
    if had_windows:
        logger.info("permission window: closed all session=%s reason=%s", session_id, reason)
    _publish(session_id)
    _tell_closed(session_id)      # also when only a plan approval was open: the kept texts wait for it too


def _close(session_id: str, tab: _TabWindows, window: Window, reason: str) -> None:
    tab.windows.remove(window)
    if not any(each.is_permission for each in tab.windows):
        tab.answered_in_batch = 0
    logger.info("permission window: closed session=%s number=%d tool=%s reason=%s", session_id, window.number,
                window.tool_name, reason)
    _publish(session_id)
    _tell_closed(session_id)


def _tell_closed(session_id: str) -> None:
    for listener in list(_close_listeners):
        listener(session_id)


def note_plan_cleared(session_id: str) -> None:
    """The plan approval of the tab was answered: what waited for it may be typed now."""
    _tell_closed(session_id)
