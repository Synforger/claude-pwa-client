"""Looks at the pane just before a key is typed into a tab and types it, or says why not: the answer to a permission window,
and the look before every other text or key a window may be in the way of.

The look and the key are one step under the tab's typing lock (`terminal/pane_order.py`), so the screen cannot change
between them. A window is answered only when the judgement says so (`window_judgement.judge`: the screen shows it, the
record says it is an approval, it offers `Yes` and `No` only, the hook's command is on the screen whole, and the screen has
shown it since the last answer); the key is the line labelled `Yes` or `No`, read from the screen, with no Enter and no
Escape. The window is closed once the key is typed, without waiting for the record.

Used by `routes/permission_window.py`, `terminal/routes.py` (the person's answer words, and the check before a send) and
`terminal/receipt.py`.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from backend.permission_window import window_hold, window_state
from backend.permission_window.answer_words import key_for
from backend.permission_window.window_judgement import Action, Caller, Kind, WindowInTheWay, judge
from backend.permission_window.window_screen import ScreenKind, ScreenReading, read_screen
from backend.terminal import runner
from backend.terminal.ansi_text import strip_ansi
from backend.terminal.pane_order import in_typing_order
from backend.terminal.prompt_detector_loop import note_user_input, poke_now

logger = logging.getLogger(__name__)

CLOSED = {"ok": False, "reason": "closed"}
MISMATCH = {"ok": False, "reason": "mismatch"}
NOT_TYPED = {"ok": False, "reason": "not_typed"}


def look(session_id: str) -> ScreenReading:
    """The pane's screen read now (= one tmux capture; blocks). An unreadable pane reads as neither window nor input box."""
    return read_screen(strip_ansi(runner.capture_pane_ansi_tail(session_id) or ""))


def check_before_typing(session_id: str, caller: Caller, *, releasing: bool = False) -> Callable[[], None]:
    """The look to make inside the typing lock before `caller` types into the tab: it raises `WindowInTheWay` when the
    judgement is not to type. `releasing` is the typing of the messages kept, which are the backlog themselves."""
    def check() -> None:
        reading = look(session_id)
        backlog = not releasing and window_hold.has_kept(session_id)
        action = judge(caller, window_state.situation(session_id, reading, backlog=backlog))
        if action is Action.TYPE:
            return
        # Typing the kept messages first is the caller's to do, before it takes the lock: here the message waits behind them.
        raise WindowInTheWay(Action.HOLD if action is Action.RELEASE_THEN_TYPE else action)
    return check


def _answer_once(session_id: str, number: int, answer_kind: str) -> tuple[dict, str]:
    """The look and the key, under the lock. → the answer, and the fingerprint of the screen the key was typed at."""
    reading = look(session_id)
    window = window_state.current_window(session_id)
    if window is None or window.number != number:
        return {"ok": False, "reason": "stale", "current": window.number if window is not None else None}, ""
    situation = window_state.situation(session_id, reading)
    if judge(Caller.ANSWER, situation) is not Action.TYPE:
        closed = reading.kind is not ScreenKind.WINDOW or situation.kind is not Kind.APPROVAL
        logger.info("permission window: not answered session=%s number=%d reason=%s", session_id, number,
                    "closed" if closed else "mismatch")
        return dict(CLOSED if closed else MISMATCH), ""
    key = key_for(reading.choices, answer_kind)
    if key is None or not runner.tmux_send_keys(session_id, text=key):
        return dict(NOT_TYPED), ""
    return {"ok": True, "key": key}, reading.fingerprint


async def answer(session_id: str, number: int, answer_kind: str) -> dict:
    """Answer the permission window `number` (the oldest the client knows of) with `ALLOW` or `DENY` of `answer_words`.
    → `{"ok": True}`, or `{"ok": False, "reason": "closed" | "mismatch" | "not_typed"}`, or `reason` `stale` with the
    `current` number when the window is not the one named."""
    if window_state.current_window(session_id) is None or not window_state.is_open(session_id):
        return dict(CLOSED)
    result, fingerprint = await in_typing_order(session_id, lambda: _answer_once(session_id, number, answer_kind))
    if not result.get("ok"):
        return result
    logger.info("permission window: answered session=%s number=%d answer=%s key=%s", session_id, number, answer_kind,
                result["key"])
    window_state.note_answered(session_id, number, fingerprint)
    note_user_input(session_id)
    asyncio.create_task(poke_now(session_id))
    return {"ok": True}


async def answer_with_word(session_id: str, answer_kind: str) -> bool:
    """A person's answer word: answer the window the client knows of now. False when there is none to answer (the words are
    then an utterance like any other)."""
    window = window_state.current_window(session_id)
    if window is None or not window_state.is_open(session_id):
        return False
    return bool((await answer(session_id, window.number, answer_kind)).get("ok"))
