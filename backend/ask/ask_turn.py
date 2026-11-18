"""Type one text into a tab whose agent takes asks, and give back the last answer of that turn. Called by `routes/ask.py`.

An ask is a program's question to a Claude Code tab it uses as its model. The text goes in as plain input (= no
envelope, unlike a message from another tab), and the answer is what the `Stop` hook says the turn ended with. Plain
input is what the operator's own words look like, so only an agent with `"ask": true` in the client's configuration
takes asks: a tab set up for a program, not one an agent works in.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException

from backend._common.errors import raise_error
from backend.account_hold import hold_mail
from backend.ask import turn_waiters
from backend.routes.agent_messages import deliver_message, resolve_receiver, wake_tab
from backend.routes.overview import is_busy
from backend.terminal.pty_discover import claude_in_pane
from backend.terminal.routes import pty_send
from backend.terminal.session_resolver import resolve_agent_cfg

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SEC = 180.0
MAX_TIMEOUT_SEC = 3600.0
#: How long a `/clear` gets to open the new conversation (= the `SessionStart` hook comes within a second or two)
CLEAR_WAIT_SEC = 30.0
CLEAR_COMMAND = "/clear"

#: The failures of the delivery shared with the messages between tabs (`routes/agent_messages.py`), as the asker's
#: codes. Any other code of that door means the text may have been typed: `ask_unconfirmed`.
_DELIVERY_CODES: dict[str, tuple[int, str]] = {
    "agent_message_receiver_not_running": (409, "ask_not_ready"),
    "agent_message_receiver_not_ready": (409, "ask_not_ready"),
    "agent_message_not_taken": (409, "ask_not_ready"),
    "agent_message_not_sent": (409, "ask_not_ready"),
    "agent_message_unknown_receiver": (404, "ask_unknown_tab"),
    "agent_message_ambiguous_receiver": (409, "ask_ambiguous_tab"),
    "agent_message_api_tab": (403, "ask_not_allowed"),
}


def takes_asks(session_id: str) -> bool:
    """Whether the tab's agent is set up to take asks (= `"ask": true`)."""
    return (resolve_agent_cfg(session_id) or {}).get("ask") is True


async def ask(to: str, text: str, *, fresh: bool = False, timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> dict:
    """Ask the tab `to` (= its id or name) `text` and wait for the turn's last answer.

    `fresh` types `/clear` first, so the turn sees nothing of the asks before it. A turn that has not ended within
    `timeout_sec` of the typing is stopped (= Escape), so that the tab is free for the next ask.
    → `{"ok": True, "id": <tab id>, "answer": <text>}`; failures are HTTP errors with an `ask_*` code."""
    with _as_ask_error():
        session_id = resolve_receiver(to)
    if not takes_asks(session_id):
        raise_error(403, "ask_not_allowed",
                    f"このタブのエージェントは聞かれる設定 (= \"ask\": true) を持っていません: {session_id}", id=session_id)
    waiter = turn_waiters.start_waiting(session_id)
    if waiter is None:
        raise_error(409, "ask_in_progress", f"このタブには別の問いの答えを待っています。 答えが返ってから聞いてください: {session_id}",
                    id=session_id)
    try:
        answer = await _ask(session_id, text, waiter, fresh=fresh, timeout_sec=timeout_sec)
    finally:
        turn_waiters.stop_waiting(session_id, waiter)
    return {"ok": True, "id": session_id, "answer": answer}


async def _ask(session_id: str, text: str, waiter: turn_waiters.TurnWaiter, *, fresh: bool, timeout_sec: float) -> str:
    if await asyncio.to_thread(hold_mail.must_keep, session_id):
        raise_error(409, "ask_held", "このタブは口座の止める線で止まっていて、 動ける口座がありません。 何も聞いていません", id=session_id)
    with _as_ask_error():
        woke = await wake_tab(session_id)
    if is_busy(session_id):
        raise_error(409, "ask_tab_busy", "このタブは別の仕事の途中です。 何も聞いていません。 終わってから聞いてください", id=session_id)
    # A tab with no claude yet starts a new conversation with the text itself: there is nothing to clear.
    cleared = fresh and claude_in_pane(session_id)
    if cleared:
        await _clear(session_id, waiter)
    answer = turn_waiters.expect_answer(waiter)
    with _as_ask_error():
        await deliver_message(session_id, text, woke and not cleared)
    logger.info("ask: typed %d chars into session=%s fresh=%s; waiting up to %.0fs", len(text), session_id, cleared,
                timeout_sec)
    try:
        return await asyncio.wait_for(asyncio.shield(answer), timeout_sec)
    except asyncio.TimeoutError:
        stopped = (await pty_send(session_id, {"key": "Escape"}, None)).get("ok")
        logger.warning("ask: no answer within %.0fs in session=%s; turn stopped=%s", timeout_sec, session_id, stopped)
        raise_error(504, "ask_timeout",
                    f"{timeout_sec:.0f} 秒以内に答えが終わりませんでした。 "
                    + ("そのターンは止めました" if stopped else "そのターンを止められませんでした"),
                    id=session_id)
        raise AssertionError("unreachable") from None


async def _clear(session_id: str, waiter: turn_waiters.TurnWaiter) -> None:
    """Type `/clear` and wait for the new conversation to open (= its `SessionStart` hook)."""
    result = await pty_send(session_id, {"text": CLEAR_COMMAND, "enter": True}, None)
    if not result.get("ok"):
        raise_error(409, "ask_not_ready", "会話を新しくする /clear を打てませんでした。 何も聞いていません。 もう一度聞いてください",
                    id=session_id)
    try:
        await asyncio.wait_for(waiter.opened.wait(), CLEAR_WAIT_SEC)
    except asyncio.TimeoutError:
        raise_error(409, "ask_not_ready",
                    f"/clear の後、 {CLEAR_WAIT_SEC:.0f} 秒以内に新しい会話が開きませんでした。 何も聞いていません。 もう一度聞いてください",
                    id=session_id)


@contextmanager
def _as_ask_error() -> Iterator[None]:
    """Give a failure of the shared delivery the asker's code (= the message stays: it says what to do next)."""
    try:
        yield
    except HTTPException as error:
        detail = error.detail if isinstance(error.detail, dict) else {}
        code = str(detail.get("code") or "")
        if not code.startswith("agent_message_"):
            raise
        status, ask_code = _DELIVERY_CODES.get(code, (500, "ask_unconfirmed"))
        raise_error(status, ask_code, str(detail.get("message", "")), cause=code)
