"""The waits of the asks in flight: one per tab, ended by that tab's hooks.

`ask_turn.ask` starts a wait before it types into the tab; the `Stop` hook hands over the turn's last answer and the
`SessionStart` hook says a conversation has opened (= after `/clear`, `/resume` or `/branch`; `routes/hooks.py` calls
in here). A hook of a tab with no ask in flight changes nothing.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable


class TurnWaiter:
    """One ask's wait on its tab: the answer of the turn it typed (and the conversation it was in), and the
    conversations that opened while it waited (= each `SessionStart`, with the conversation's id when the hook had one)."""

    def __init__(self) -> None:
        self.answer: asyncio.Future[str] | None = None
        self.claude_session_id: str | None = None
        self.openings: list[str | None] = []
        self._opened = asyncio.Event()

    async def wait_opening(self, after: int, accept: Callable[[str | None], bool], timeout_sec: float) -> bool:
        """Wait for a conversation to open that `accept` takes (= it is given the id, or None when the hook sent none),
        among the openings after the first `after` ones. → whether one did within `timeout_sec`. `after` is
        `len(openings)` taken right before the typing that should open the conversation."""
        deadline = asyncio.get_running_loop().time() + timeout_sec
        while True:
            for opened in self.openings[after:]:
                if accept(opened):
                    return True
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return False
            self._opened.clear()
            try:
                await asyncio.wait_for(self._opened.wait(), remaining)
            except asyncio.TimeoutError:
                pass

    def note_opening(self, claude_session_id: str | None) -> None:
        self.openings.append(claude_session_id)
        self._opened.set()


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


def turn_ended(session_id: str, text: str, claude_session_id: str | None = None) -> None:
    """The tab's turn ended with `text` as its last answer (= the `Stop` hook). `claude_session_id` is the id of the
    Claude Code conversation the turn was in (= the hook's `session_id`), kept on the wait for the ask to hand on."""
    waiter = _waiters.get(session_id)
    if waiter is not None and waiter.answer is not None and not waiter.answer.done():
        waiter.claude_session_id = claude_session_id
        waiter.answer.set_result(text)


def conversation_opened(session_id: str, claude_session_id: str | None = None) -> None:
    """A conversation opened in the tab (= the `SessionStart` hook: also after `/clear`, `/resume` and `/branch`).
    `claude_session_id` is the opened conversation's id (= the hook's `session_id`)."""
    waiter = _waiters.get(session_id)
    if waiter is not None:
        waiter.note_opening(claude_session_id)
