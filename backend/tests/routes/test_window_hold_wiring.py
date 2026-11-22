"""What the kept messages are typed and told with (`routes/window_hold_wiring.py`): typed as a message of a person or another
tab, and a sender that is another tab is told in one line by the client when its message did not arrive."""
from __future__ import annotations

import pytest

import backend.accounts.client_message as client_message
import backend.routes.window_hold_wiring as wiring
from backend._common.state import SessionDef, sessions_meta
from backend.permission_window import window_hold
from backend.tests.async_run import run


@pytest.fixture
def tabs(monkeypatch):
    monkeypatch.setitem(sessions_meta, "ses_sender", SessionDef(id="ses_sender", agent_id="a", title="tools", created_at=0))
    monkeypatch.setitem(sessions_meta, "ses_receiver", SessionDef(id="ses_receiver", agent_id="a", title="client work", created_at=0))
    told = []

    async def send_to_tab(session_id, text):
        told.append((session_id, text))
        return True
    monkeypatch.setattr(client_message, "send_to_tab", send_to_tab)
    return told


def test_the_notice_is_the_clients_own_and_names_the_tab_the_text_and_why(tabs):
    run(wiring._tell_sender("ses_sender", "ses_receiver", "please run the check\nand tell me", window_hold.OTHER_CONVERSATION))
    [(to, text)] = tabs
    assert to == "ses_sender" and text.startswith("Sent by the client (the operator did not type this):")
    assert '<message-not-delivered to="client work" reason="other_conversation">' in text
    assert 'begins "please run the check and tell me"' in text and "another conversation" in text


def test_a_long_text_is_quoted_in_part(tabs):
    run(wiring._tell_sender("ses_sender", "ses_receiver", "x" * 500, window_hold.NO_CLAUDE))
    assert "x" * wiring.QUOTE_CHARS in tabs[0][1] and "x" * (wiring.QUOTE_CHARS + 1) not in tabs[0][1]


def test_a_sleeping_sender_is_not_woken_for_it(tabs, monkeypatch):
    from backend._common.state import SleepMark
    monkeypatch.setattr(sessions_meta["ses_sender"], "sleep", SleepMark(claude_sid="c", record="r", slept_at=0))
    run(wiring._tell_sender("ses_sender", "ses_receiver", "text", window_hold.NO_CLAUDE))
    assert tabs == []


def test_a_sender_that_is_gone_is_not_told(tabs):
    run(wiring._tell_sender("ses_gone", "ses_receiver", "text", window_hold.NO_CLAUDE))
    assert tabs == []


def test_the_kept_message_is_typed_as_a_message_that_may_be_kept_again_by_a_window(monkeypatch):
    seen = []

    async def pty_send(session_id, payload, key=None, **kwargs):
        seen.append((session_id, payload, kwargs))
        return {"ok": True}
    monkeypatch.setattr(wiring, "pty_send", pty_send)
    run(wiring._type_kept("ses_receiver", "text", "ses_sender"))
    assert seen == [("ses_receiver", {"text": "text", "enter": True},
                     {"hold": True, "sender": "ses_sender", "releasing": True})]


def test_the_package_is_given_what_it_types_looks_and_tells_with():
    assert window_hold._wiring is not None
