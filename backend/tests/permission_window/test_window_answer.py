"""Answering a window by a key: the look at the screen and the key are one step, and the answer is typed only when the
screen, the record and the hook agree (`permission_window/window_answer.py`, `routes/permission_window.py`)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.permission_window.window_answer as window_answer
import backend.routes.permission_window as door
import backend.terminal.runner as runner
from backend.permission_window import window_state as state
from backend.permission_window.answer_words import ALLOW, DENY
from backend.permission_window.window_judgement import Caller, WindowInTheWay
from backend.permission_window.window_screen import read_screen
from backend.tests.async_run import run
from backend.tests.permission_window import screens
from backend.tests.permission_window.conftest import SID, call_row

LS = {"command": "ls -la"}


@pytest.fixture
def pane(monkeypatch):
    shown = {"text": screens.approval("ls -la"), "typed": []}
    monkeypatch.setattr(runner, "capture_pane_ansi_tail", lambda _sid, lines=70: shown["text"])
    monkeypatch.setattr(runner, "tmux_send_keys",
                        lambda _sid, text=None, key=None, enter=False: shown["typed"].append((text, key, enter)) or True)
    monkeypatch.setattr(window_answer, "note_user_input", lambda _sid: None)

    async def poke(_sid):
        return None
    monkeypatch.setattr(window_answer, "poke_now", poke)
    return shown


def an_open_window(pane, command="ls -la", *, tool_use_id="toolu_1", hook=True):
    """The call in the record, the hook's input, and the detector's look at the window on the screen."""
    state.fold_row(SID, call_row(tool_use_id, "Bash", {"command": command}))
    if hook:
        state.open_window(SID, "Bash", {"command": command}, "p1", now=1.0)
    state.note_screen(SID, read_screen(pane["text"]))
    return state.current_window(SID)


def answer(number, kind=ALLOW):
    return run(window_answer.answer(SID, number, kind))


def test_allow_types_the_key_of_the_yes_line_without_enter(pane):
    window = an_open_window(pane)
    assert answer(window.number) == {"ok": True}
    assert pane["typed"] == [("1", None, False)]


def test_deny_types_the_key_of_the_no_line(pane):
    window = an_open_window(pane)
    answer(window.number, DENY)
    assert pane["typed"] == [("2", None, False)]


def test_a_window_whose_choices_are_not_yes_then_no_is_answered_at_the_terminal(pane):
    pane["text"] = screens.approval("ls -la").replace(" ❯ 1. Yes\n   2. No", " ❯ 1. No\n   2. Yes")
    window = an_open_window(pane)
    assert answer(window.number) == {"ok": False, "reason": "mismatch"} and pane["typed"] == []


def test_the_window_is_closed_as_soon_as_the_key_is_typed(pane, tab):
    window = an_open_window(pane)
    answer(window.number)
    assert state.is_open(SID) is False and tab["pending_permission"] is None


def test_a_tab_with_no_window_is_closed_and_nothing_is_typed(pane):
    pane["text"] = screens.idle()
    assert answer(1) == {"ok": False, "reason": "closed"} and pane["typed"] == []


def test_a_window_that_is_gone_from_the_screen_is_closed_and_nothing_is_typed(pane):
    window = an_open_window(pane)
    pane["text"] = screens.idle()
    assert answer(window.number) == {"ok": False, "reason": "closed"} and pane["typed"] == []


def test_b_the_command_on_the_screen_is_compared_with_the_hooks_input(pane):
    """Red before the fix: a key was typed for a window whose command was not the one the hook gave."""
    window = an_open_window(pane, command="rm -rf /")
    pane["text"] = screens.approval("ls -la")
    state.note_screen(SID, read_screen(pane["text"]))
    assert answer(window.number) == {"ok": False, "reason": "mismatch"} and pane["typed"] == []


def test_a_command_the_dialog_cuts_short_is_not_answered(pane):
    command = "echo hello world && cat /etc/hosts"
    pane["text"] = screens.cut_short(command)
    window = an_open_window(pane, command=command)
    assert answer(window.number)["reason"] == "mismatch" and pane["typed"] == []


def test_three_choices_are_answered_at_the_terminal_and_no_escape_is_typed(pane):
    pane["text"] = screens.three_choices()
    window = an_open_window(pane)
    assert answer(window.number, DENY) == {"ok": False, "reason": "mismatch"} and pane["typed"] == []


def test_a_window_the_detector_has_not_shown_is_not_answered(pane):
    state.fold_row(SID, call_row("toolu_1", "Bash", LS))
    state.open_window(SID, "Bash", LS, "p1", now=1.0)
    assert answer(1)["reason"] == "closed" and pane["typed"] == []


def test_a_window_with_no_hook_is_shown_and_is_not_answered_by_a_key(pane):
    window = an_open_window(pane, hook=False)
    assert answer(window.number)["reason"] == "mismatch" and pane["typed"] == []


def test_a_the_second_answer_waits_for_the_screen_to_show_the_next_window(pane):
    """Red before the fix: a second answer typed a key at a window nobody had seen."""
    state.fold_row(SID, call_row("toolu_1", "Bash", {"command": "ls"}))
    state.fold_row(SID, call_row("toolu_2", "Bash", {"command": "pwd"}))
    pane["text"] = screens.approval("ls", position=" (1 of 2)")
    first = state.open_window(SID, "Bash", {"command": "ls"}, "p1", now=1.0)
    second = state.open_window(SID, "Bash", {"command": "pwd"}, "p1", now=1.0)
    state.note_screen(SID, read_screen(pane["text"]))
    assert answer(first.number) == {"ok": True}
    # no look has shown the next window yet: the first is still drawn
    assert answer(second.number)["ok"] is False
    pane["text"] = screens.approval("pwd", position=" (2 of 2)")
    state.note_screen(SID, read_screen(pane["text"]))
    assert answer(second.number) == {"ok": True}
    assert pane["typed"] == [("1", None, False), ("1", None, False)]


def test_a_the_second_of_two_windows_that_look_the_same_is_not_answered_on_the_look_of_the_first(pane):
    """Two windows for the same command look alike: the first answer is typed, and the second window is answered only once the
    screen has shown another window after it (the command being the same, only the look says so)."""
    for tool_use_id in ("toolu_1", "toolu_2"):
        state.fold_row(SID, call_row(tool_use_id, "Bash", LS))
    first = state.open_window(SID, "Bash", LS, "p1", now=1.0)
    second = state.open_window(SID, "Bash", LS, "p1", now=1.0)
    state.note_screen(SID, read_screen(pane["text"]))
    assert answer(first.number) == {"ok": True}
    state.note_screen(SID, read_screen(pane["text"]))       # the first window is still drawn
    assert answer(second.number) == {"ok": False, "reason": "mismatch"}
    assert pane["typed"] == [("1", None, False)]
    state.note_screen(SID, read_screen(screens.idle()))      # the screen changed ...
    state.note_screen(SID, read_screen(pane["text"]))        # ... and shows a window again
    assert answer(second.number) == {"ok": True}


def test_e_numbers_in_a_reply_are_not_a_window_to_answer(pane):
    """Red before the fix: `1. Yes` and `2. No` in a reply were read as the window's choices."""
    window = an_open_window(pane)
    pane["text"] = screens.numbers_in_a_reply()
    assert answer(window.number) == {"ok": False, "reason": "closed"} and pane["typed"] == []


def test_a_key_tmux_does_not_take_is_not_typed(pane, monkeypatch):
    window = an_open_window(pane)
    monkeypatch.setattr(runner, "tmux_send_keys", lambda *args, **kwargs: False)
    assert answer(window.number) == {"ok": False, "reason": "not_typed"}
    assert state.is_open(SID)


def test_an_answer_word_answers_the_window_the_client_knows_of(pane):
    an_open_window(pane)
    assert run(window_answer.answer_with_word(SID, DENY)) is True
    assert pane["typed"] == [("2", None, False)]


def test_an_answer_word_with_no_window_answers_nothing(pane):
    assert run(window_answer.answer_with_word(SID, ALLOW)) is False and pane["typed"] == []


def test_the_check_before_typing_stops_a_message_at_an_approval_window_and_lets_it_through_at_the_input_box(pane):
    an_open_window(pane)
    with pytest.raises(WindowInTheWay):
        window_answer.check_before_typing(SID, Caller.MESSAGE)()
    pane["text"] = screens.idle()
    window_answer.check_before_typing(SID, Caller.MESSAGE)()


@pytest.fixture
def client(pane, monkeypatch):
    app = FastAPI()
    app.include_router(door.router)
    return TestClient(app)


def post(client, number, answer_word, session=SID, path="pty"):
    return client.post(f"/{path}/{session}/permission/answer", json={"number": number, "answer": answer_word})


def test_the_door_is_under_pty_and_answers_the_window_it_names(client, pane):
    window = an_open_window(pane)
    reply = post(client, window.number, "allow")
    assert (reply.status_code, reply.json()) == (200, {"ok": True})
    assert pane["typed"] == [("1", None, False)]


def test_the_old_door_under_sessions_is_not_there(client, pane):
    window = an_open_window(pane)
    assert post(client, window.number, "allow", path="sessions").status_code in (404, 405)
    assert pane["typed"] == []


def test_the_door_says_closed_when_the_tab_has_no_window(client, pane):
    pane["text"] = screens.idle()
    assert post(client, 1, "allow").json() == {"ok": False, "reason": "closed"}


def test_the_door_says_mismatch_for_a_window_a_key_does_not_answer(client, pane):
    pane["text"] = screens.three_choices()
    window = an_open_window(pane)
    assert post(client, window.number, "allow").json() == {"ok": False, "reason": "mismatch"}


def test_the_door_refuses_an_old_number_with_409(client, pane):
    window = an_open_window(pane)
    reply = post(client, window.number + 5, "deny")
    assert reply.status_code == 409 and reply.json()["detail"]["code"] == "permission_stale"
    assert pane["typed"] == [] and state.is_open(SID)


def test_the_door_refuses_a_word_that_is_not_an_answer(client):
    assert post(client, 1, "maybe").status_code == 422


def test_the_door_knows_no_tab_it_was_not_told_of(client):
    assert post(client, 1, "allow", session="ses_none").status_code == 404
