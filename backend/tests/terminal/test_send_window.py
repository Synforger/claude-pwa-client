"""What is typed to a tab while Claude Code has a window open (`terminal/routes.py`, `permission_window/`).

The Enter of a text typed at a permission window confirms its first choice and the text is lost, so the text is kept
and typed once the window is gone; the person's own answer words answer the window instead of being sent; a voice never
types an Escape at it. tmux and claude are not started: the pane of `test_send_one_at_a_time` records the keys.
"""
from __future__ import annotations

import pytest

import backend.permission_window.window_answer as window_answer
import backend.terminal.routes as routes
from backend._common.state import agent_status
from backend.permission_window import window_hold, window_state
from backend.tests.async_run import run
from backend.tests.terminal.test_send_one_at_a_time import pane, send  # noqa: F401  (pane is a fixture)

SID = "ses_a"
LS = {"command": "ls"}


@pytest.fixture
def window(pane, monkeypatch):  # noqa: F811
    """The tab `ses_a` with a permission window open, and the pane drawing it."""
    monkeypatch.setitem(agent_status, SID, {"pending_plan": None, "pending_permission": None})
    monkeypatch.setattr(window_state, "_tabs", {})
    monkeypatch.setattr(window_state, "_close_listeners", [])
    monkeypatch.setattr(window_hold, "_kept", {})
    monkeypatch.setattr(window_hold, "_typers", {})
    window_hold.install(routes._type_kept_text)
    drawn = {"pane": " ❯ 1. Yes\n   2. No\n Esc to cancel", "answers": []}
    monkeypatch.setattr(window_answer, "capture_pane_ansi_tail", lambda _sid: drawn["pane"])
    monkeypatch.setattr(window_answer, "tmux_send_keys",
                        lambda session_id, text=None, key=None, enter=False: pane["keys"].append((session_id, f"answer:{text or key}")) or True)
    monkeypatch.setattr(window_answer, "note_user_input", lambda _sid: None)

    async def poke(_sid):
        return None
    monkeypatch.setattr(window_answer, "poke_now", poke)
    window_state.fold_row(SID, {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": LS}]}})
    drawn["window"] = window_state.open_window(SID, "Bash", LS, now=1.0)
    return drawn


def typed_keys(pane):  # noqa: F811
    return [what for _sid, what in pane["keys"]]


def test_a_text_is_kept_while_a_window_is_open_and_nothing_is_typed(pane, window):
    result = run(send(SID, "a message from another tab"))
    assert result == {"ok": True, "held": "window"}
    assert pane["keys"] == [] and pane["delivered"] == []


def test_the_kept_text_is_typed_once_the_window_is_gone(pane, window):
    async def scenario():
        await send(SID, "a message from another tab")
        window_state.close_all(SID, "test")
        for _ in range(60):
            await routes.asyncio.sleep(0.01)
    run(scenario())
    assert [said for _sid, said in pane["delivered"]] == ["a message from another tab"]


def test_a_single_key_is_not_kept(pane, window):
    """The number of a question is typed as it is, not kept behind the window."""
    assert run(routes.pty_send(SID, {"text": "2"}, None)) == {"ok": True}
    assert typed_keys(pane) == ["paste:2"]


def test_a_text_without_a_window_is_typed_as_before(pane, window):
    window_state.close_all(SID, "test")
    run(send(SID, "plain"))
    assert [said for _sid, said in pane["delivered"]] == ["plain"]


def test_a_plan_approval_keeps_the_text_too(pane, window):
    window_state.close_all(SID, "test")
    agent_status[SID]["pending_plan"] = {"tool_use_id": "toolu_p", "plan": "x", "choices": []}
    assert run(send(SID, "typed at the plan")) == {"ok": True, "held": "window"}


def test_the_answer_word_of_a_person_answers_the_window_and_is_not_sent(pane, window):
    window["window"].seen = True
    result = run(routes.pty_send_from_person(SID, {"text": "許可", "enter": True}, None))
    assert result == {"ok": True, "answered": "allow", "message": "窓に答えました"}
    assert typed_keys(pane) == ["answer:1"]
    assert pane["delivered"] == []
    assert window_state.is_open(SID) is False


def test_deny_words_answer_with_the_no_line(pane, window):
    window["window"].seen = True
    run(routes.pty_send_from_person(SID, {"text": "だめ", "enter": True}, None))
    assert typed_keys(pane) == ["answer:2"]


def test_an_answer_word_before_the_pane_shows_the_window_is_kept_not_counted(pane, window):
    result = run(routes.pty_send_from_person(SID, {"text": "許可", "enter": True}, None))
    assert result == {"ok": True, "held": "window"}
    assert pane["keys"] == []


def test_yes_in_japanese_is_not_an_answer(pane, window):
    window["window"].seen = True
    result = run(routes.pty_send_from_person(SID, {"text": "はい", "enter": True}, None))
    assert result == {"ok": True, "held": "window"}
    assert pane["keys"] == []


def test_an_answer_word_with_no_choices_on_the_pane_is_kept(pane, window):
    window["window"].seen = True
    window["pane"] = "● running\n"
    result = run(routes.pty_send_from_person(SID, {"text": "許可", "enter": True}, None))
    assert result == {"ok": True, "held": "window"}


def test_a_voice_never_types_an_escape_at_a_window(pane, window, monkeypatch):
    from backend._common.state import StreamState
    monkeypatch.setattr(routes, "stream_states", {SID: StreamState(busy=True)})
    assert run(routes.interrupt_for_voice(SID)) is False
    assert "key:Escape" not in typed_keys(pane)


def test_a_voice_text_is_kept_without_an_escape(pane, window, monkeypatch):
    from backend._common.state import StreamState
    monkeypatch.setattr(routes, "stream_states", {SID: StreamState(busy=True)})
    result = run(send(SID, routes.VOICE_INPUT_MARK + " please go on"))
    assert result == {"ok": True, "held": "window"}
    assert typed_keys(pane) == []
