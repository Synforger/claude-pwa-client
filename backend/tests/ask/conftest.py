"""The made-up tab every ask test types into (`backend/ask/`): its agent, delivery, keys, hooks and record."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from backend._common.errors import raise_error
from backend.ask import ask_turn, limit_watch, turn_waiters

TAB = "ses_head"
NAME = "Talemate の頭"


@pytest.fixture
def head(monkeypatch):
    """A tab of an agent that takes asks; what was typed into it, and how it answers. `record` is the path of its
    conversation record (None = no record); `after_typing` and `after_escape` run when the text goes in and when
    Escape is pressed (= what Claude Code writes to the record then)."""
    tab = SimpleNamespace(typed=[], keys=[], config={"ask": True}, running=True, busy=False, held=False, woke=False,
                          answer="the answer", answers=True, opens=True, stray_stop_on_clear=True, delivery_error=None,
                          record=None, after_typing=None, after_escape=None, claude_session=None, opened_as=None,
                          branch_id="branch-uuid")

    def resolve(to: str) -> str:
        if to in (TAB, NAME):
            return TAB
        raise_error(404, "agent_message_unknown_receiver", f"no tab {to}")
        raise AssertionError

    async def wake(session_id: str) -> bool:
        return tab.woke

    async def deliver(session_id: str, text: str, woke: bool) -> dict:
        if tab.delivery_error is not None:
            raise_error(*tab.delivery_error)
        tab.typed.append((text, woke))
        if tab.after_typing is not None:
            tab.after_typing()
        if tab.answers:
            asyncio.get_running_loop().call_soon(turn_waiters.turn_ended, session_id, tab.answer, tab.claude_session)
        return {"ok": True}

    async def send(session_id: str, payload: dict, idempotency_key) -> dict:
        if payload.get("key"):
            tab.keys.append(payload["key"])
            if tab.after_escape is not None:
                tab.after_escape()
            return {"ok": True}
        text = payload["text"]
        tab.typed.append((text, None))
        loop = asyncio.get_running_loop()
        if text == "/clear" and tab.stray_stop_on_clear:
            loop.call_soon(turn_waiters.turn_ended, session_id, "a stop that is not the answer")
        if tab.opens:
            if text == "/clear":
                loop.call_soon(turn_waiters.conversation_opened, session_id)
            elif text.startswith("/resume "):
                loop.call_soon(turn_waiters.conversation_opened, session_id, tab.opened_as or text.split()[1])
            elif text == "/branch":
                loop.call_soon(turn_waiters.conversation_opened, session_id, tab.branch_id)
        return {"ok": True}

    monkeypatch.setattr(ask_turn, "resolve_receiver", resolve)
    monkeypatch.setattr(ask_turn, "takes_asks", lambda session_id: tab.config.get("ask") is True)
    monkeypatch.setattr(ask_turn, "wake_tab", wake)
    monkeypatch.setattr(ask_turn, "deliver_message", deliver)
    monkeypatch.setattr(ask_turn, "pty_send", send)
    monkeypatch.setattr(ask_turn, "is_busy", lambda session_id: tab.busy)
    monkeypatch.setattr(ask_turn, "claude_in_pane", lambda session_id: tab.running)
    monkeypatch.setattr(ask_turn.hold_mail, "must_keep", lambda session_id: tab.held)
    monkeypatch.setattr(turn_waiters, "_waiters", {})
    monkeypatch.setattr(limit_watch.jsonl_watcher, "get_jsonl_for", lambda session_id: tab.record)
    return tab
