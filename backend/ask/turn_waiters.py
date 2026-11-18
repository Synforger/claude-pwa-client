"""The waits of the asks in flight: one per tab, ended by that tab's hooks.

`ask_turn.ask` starts a wait before it types into the tab; the `Stop` hook hands over the turn's last answer and the
`SessionStart` hook says a cleared conversation has opened (`routes/hooks.py` calls in here). A hook of a tab with no
ask in flight changes nothing.
"""
from __future__ import annotations

import asyncio


class TurnWaiter:
    """One ask's wait on its tab: the answer of the turn it typed, and the opening of the conversation it cleared."""

    def __init__(self) -> None:
        self.answer: asyncio.Future[str] | None = None
        self.opened = asyncio.Event()


_waiters: dict[str, TurnWaiter] = {}


def start_waiting(session_id: str) -> TurnWaiter | None:
    """A new wait on the tab. → None when another ask already waits on it (= one ask at a time per tab)."""
    if session_id in _waiters:
        return None
    waiter = TurnWaiter()
    _waiters[session_id] = waiter
    return waiter


def expect_answer(waiter: TurnWaiter) -> asyncio.Future[str]:
    """Take the next turn's answer from here on. Set right before the ask's text is typed, so that nothing typed
    before it (= a `/clear`) can be taken for the answer."""
    waiter.answer = asyncio.get_running_loop().create_future()
    return waiter.answer


def stop_waiting(session_id: str, waiter: TurnWaiter) -> None:
    """End the wait (= the ask answered, failed or gave up)."""
    if _waiters.get(session_id) is waiter:
        del _waiters[session_id]


def turn_ended(session_id: str, text: str) -> None:
    """The tab's turn ended with `text` as its last answer (= the `Stop` hook)."""
    waiter = _waiters.get(session_id)
    if waiter is not None and waiter.answer is not None and not waiter.answer.done():
        waiter.answer.set_result(text)


def conversation_opened(session_id: str) -> None:
    """A conversation opened in the tab (= the `SessionStart` hook, also after `/clear`)."""
    waiter = _waiters.get(session_id)
    if waiter is not None:
        waiter.opened.set()
