"""Answering the window the pane shows (`permission_window/window_answer.py`) and its door."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.permission_window.window_answer as window_answer
import backend.routes.permission_window as door
from backend._common.state import sessions_meta
from backend.permission_window import window_state as state
from backend.permission_window.answer_words import ALLOW, DENY
from backend.tests.async_run import run
from backend.tests.permission_window.conftest import SID, call_row

WINDOW_PANE = ("Hook PreToolUse:Bash requires confirmation for this command: guard says so\n"
               " ❯ 1. Yes\n   2. No\n\n Esc to cancel · Tab to amend")
SWAPPED_PANE = "  1. No\n ❯ 2. Yes\n"
NO_NO_LINE = " ❯ 1. Yes\n   2. Yes, and don't ask again\n"


@pytest.fixture
def pane(monkeypatch):
    shown = {"text": WINDOW_PANE, "typed": []}

    def type_key(session_id, text=None, key=None, enter=False):
        shown["typed"].append((text, key, enter))
        return True
    monkeypatch.setattr(window_answer, "capture_pane_ansi_tail", lambda _sid: shown["text"])
    monkeypatch.setattr(window_answer, "tmux_send_keys", type_key)
    monkeypatch.setattr(window_answer, "note_user_input", lambda _sid: None)

    async def poke(_sid):
        return None
    monkeypatch.setattr(window_answer, "poke_now", poke)
    return shown


def a_window():
    state.fold_row(SID, call_row("toolu_1", "Bash", {"command": "ls"}))
    return state.open_window(SID, "Bash", {"command": "ls"}, now=1.0)


def test_allow_types_the_key_of_the_yes_line_without_enter(pane):
    window = a_window()
    assert run(window_answer.answer(SID, window, ALLOW)) == {"ok": True}
    assert pane["typed"] == [("1", None, False)]


def test_deny_types_the_key_of_the_no_line(pane):
    window = a_window()
    run(window_answer.answer(SID, window, DENY))
    assert pane["typed"] == [("2", None, False)]


def test_the_keys_are_read_from_the_screen_not_fixed(pane):
    pane["text"] = SWAPPED_PANE
    window = a_window()
    run(window_answer.answer(SID, window, ALLOW))
    assert pane["typed"] == [("2", None, False)]


def test_a_deny_with_no_no_line_is_an_escape(pane):
    pane["text"] = NO_NO_LINE
    window = a_window()
    run(window_answer.answer(SID, window, DENY))
    assert pane["typed"] == [(None, "Escape", False)]


def test_an_allow_with_no_yes_line_types_nothing(pane):
    pane["text"] = "  1. Maybe\n  2. No\n"
    window = a_window()
    assert run(window_answer.answer(SID, window, ALLOW)) == {"ok": False, "reason": "no_yes_line"}
    assert pane["typed"] == []


def test_a_pane_with_no_choices_is_closed_and_nothing_is_typed(pane):
    pane["text"] = "● running a command\n"
    window = a_window()
    assert run(window_answer.answer(SID, window, ALLOW)) == {"ok": False, "reason": "closed"}
    assert pane["typed"] == [] and state.is_open(SID)


def test_the_window_is_closed_as_soon_as_the_key_is_typed(pane, tab):
    window = a_window()
    run(window_answer.answer(SID, window, ALLOW))
    assert state.is_open(SID) is False and tab["pending_permission"] is None


@pytest.fixture
def client(pane, monkeypatch):
    monkeypatch.setitem(sessions_meta, SID, object())
    app = FastAPI()
    app.include_router(door.router)
    return TestClient(app)


def post(client, number, answer, session=SID):
    return client.post(f"/sessions/{session}/permission/answer", json={"number": number, "answer": answer})


def test_the_door_answers_the_window_it_names(client, pane):
    window = a_window()
    reply = post(client, window.number, "allow")
    assert (reply.status_code, reply.json()) == (200, {"ok": True})
    assert pane["typed"] == [("1", None, False)]


def test_the_door_says_closed_when_the_tab_has_no_window(client, pane):
    assert post(client, 1, "allow").json() == {"ok": False, "reason": "closed"}
    assert pane["typed"] == []


def test_the_door_refuses_an_old_number_with_409(client, pane):
    window = a_window()
    reply = post(client, window.number + 5, "deny")
    assert reply.status_code == 409
    assert reply.json()["detail"]["code"] == "permission_stale"
    assert pane["typed"] == [] and state.is_open(SID)


def test_the_door_refuses_a_word_that_is_not_an_answer(client):
    assert post(client, 1, "maybe").status_code == 422


def test_the_door_knows_no_tab_it_was_not_told_of(client):
    assert post(client, 1, "allow", session="ses_none").status_code == 404
