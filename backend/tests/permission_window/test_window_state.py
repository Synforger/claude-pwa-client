"""What the client knows of a tab's windows (`permission_window/window_state.py`): the screen says a window is open, the
record says what it is, and a hook only gives the input it shows."""
from __future__ import annotations

import json

import pytest

from backend.permission_window import window_state as state
from backend.permission_window.window_judgement import Kind
from backend.permission_window.window_screen import read_screen
from backend.tests.permission_window import screens
from backend.tests.permission_window.conftest import SID, call_row, result_row

LS = {"command": "ls -la"}


def look(text: str) -> None:
    state.note_screen(SID, read_screen(text))


def a_call(tool_use_id="toolu_1", name="Bash", tool_input=None):
    state.fold_row(SID, call_row(tool_use_id, name, LS if tool_input is None else tool_input))


def test_a_hook_alone_is_no_window(tab):
    """The hook is the input the window shows, no evidence that one is open: only the screen says that."""
    a_call()
    state.open_window(SID, "Bash", LS, "p1", now=1.0)
    assert state.is_open(SID) is False and tab["pending_permission"] is None


def test_the_window_on_the_screen_is_open_and_is_shown_with_the_hooks_input(tab):
    a_call()
    window = state.open_window(SID, "Bash", LS, "p1", now=7.0)
    look(screens.approval("ls -la"))
    assert state.is_open(SID) and state.kind_of(SID) is Kind.APPROVAL
    shown = tab["pending_permission"]
    assert (shown["number"], shown["tool_name"], shown["input"], shown["record_input"], shown["opened_at"]) == (
        window.number, "Bash", LS, None, 7.0)
    assert (shown["index"], shown["count"], shown["tool_use_id"]) == (1, 1, "toolu_1")


def test_the_input_box_ends_the_window_for_the_judgements_at_once_and_the_memory_after_two_looks(tab):
    a_call()
    state.open_window(SID, "Bash", LS, "p1", now=1.0)
    look(screens.approval("ls -la"))
    look(screens.idle())
    assert state.is_open(SID) is False and tab["pending_permission"] is None
    assert state.current_window(SID) is not None          # remembered after one look
    look(screens.idle())
    assert state.current_window(SID) is None              # forgotten after two


def test_a_window_the_hook_rewrote_shows_both_inputs():
    a_call(tool_input={"command": "echo original"})
    state.open_window(SID, "Bash", {"command": "echo rewritten"}, "p1", now=1.0)
    look(screens.approval("echo rewritten"))
    shown = state.current_window(SID)
    assert shown.tool_input == {"command": "echo rewritten"} and shown.record_input == {"command": "echo original"}


def test_two_windows_in_a_row_are_asked_in_the_order_of_the_record():
    a_call("toolu_1", tool_input={"command": "ls"})
    a_call("toolu_2", tool_input={"command": "pwd"})
    second = state.open_window(SID, "Bash", {"command": "pwd"}, "p1", now=1.0)
    first = state.open_window(SID, "Bash", {"command": "ls"}, "p1", now=1.0)
    assert (first.tool_use_id, second.tool_use_id) == ("toolu_1", "toolu_2")
    assert state.current_window(SID) is first


def test_a_window_with_no_hook_is_shown_from_the_record_and_is_not_answerable(tab):
    a_call()
    look(screens.approval("ls -la"))
    shown = tab["pending_permission"]
    assert shown["input"] == LS and shown["answerable"] is False
    assert state.current_window(SID).from_hook is False


def test_the_hook_that_comes_after_the_screen_is_the_input_the_window_shows_from_then_on(tab):
    a_call()
    look(screens.approval("ls -la"))
    number = state.current_window(SID).number
    state.open_window(SID, "Bash", LS, "p1", now=1.0)
    assert state.current_window(SID).number == number and state.current_window(SID).from_hook
    look(screens.approval("ls -la"))
    assert tab["pending_permission"]["answerable"] is True


@pytest.mark.parametrize("screen, why", [
    (screens.three_choices("ls -la"), "three choices"),
    (screens.approval("pwd"), "another command is on the screen"),
])
def test_a_window_a_key_does_not_answer_is_not_answerable(tab, screen, why):
    a_call()
    state.open_window(SID, "Bash", LS, "p1", now=1.0)
    look(screen)
    assert tab["pending_permission"]["answerable"] is False, why


def test_a_command_the_dialog_cuts_short_is_not_answerable(tab):
    long_command = {"command": "ls -la --all --long --human-readable /usr"}
    a_call(tool_input=long_command)
    state.open_window(SID, "Bash", long_command, "p1", now=1.0)
    look(screens.cut_short(long_command["command"]))
    assert tab["pending_permission"]["answerable"] is False


def test_a_window_with_no_hook_input_is_not_answerable_even_when_the_screen_matches(tab):
    a_call("toolu_1", "Edit", {"file_path": "/x"})
    state.open_window(SID, "Edit", {"file_path": "/x"}, "p1", now=1.0)
    look(screens.approval("ls -la"))
    assert tab["pending_permission"]["answerable"] is False


def test_the_answer_is_typed_for_a_window_the_screen_has_shown_since_the_last_answer():
    a_call("toolu_1", tool_input={"command": "ls"})
    a_call("toolu_2", tool_input={"command": "pwd"})
    first = state.open_window(SID, "Bash", {"command": "ls"}, "p1", now=1.0)
    state.open_window(SID, "Bash", {"command": "pwd"}, "p1", now=1.0)
    look(screens.approval("ls", position=" (1 of 2)"))
    reading = read_screen(screens.approval("ls", position=" (1 of 2)"))
    assert state.situation(SID, reading).answerable
    state.note_answered(SID, first.number, reading.fingerprint)
    # the old window is still on the screen for a moment: the next one is not answerable by what it shows
    look(screens.approval("ls", position=" (1 of 2)"))
    assert state.situation(SID, read_screen(screens.approval("pwd", position=" (2 of 2)"))).answerable is False
    look(screens.approval("pwd", position=" (2 of 2)"))
    assert state.situation(SID, read_screen(screens.approval("pwd", position=" (2 of 2)"))).answerable


def test_an_answered_call_is_no_window_while_it_runs_and_no_new_one_is_stood_up_for_it(tab):
    a_call()
    window = state.open_window(SID, "Bash", LS, "p1", now=1.0)
    reading = read_screen(screens.approval("ls -la"))
    look(screens.approval("ls -la"))
    state.note_answered(SID, window.number, reading.fingerprint)
    look(screens.approval("ls -la"))      # drawn on for a moment
    assert state.is_open(SID) is False and state.current_window(SID) is None and tab["pending_permission"] is None


def test_the_result_of_the_call_takes_its_window_away():
    a_call()
    state.open_window(SID, "Bash", LS, "p1", now=1.0)
    state.fold_row(SID, result_row("toolu_1"))
    assert state.current_window(SID) is None and state.kind_of(SID) is Kind.NONE


def test_a_hook_whose_call_has_its_result_already_is_not_kept(tab):
    a_call()
    state.fold_row(SID, result_row("toolu_1"))
    assert state.open_window(SID, "Bash", LS, "p1", now=1.0) is None


def test_the_kind_is_the_oldest_call_without_a_result():
    assert state.kind_of(SID) is Kind.NONE
    a_call("toolu_q", "AskUserQuestion", {"questions": []})
    assert state.kind_of(SID) is Kind.QUESTION
    state.fold_row(SID, result_row("toolu_q"))
    a_call("toolu_p", "ExitPlanMode", {"plan": "x"})
    assert state.kind_of(SID) is Kind.PLAN
    state.fold_row(SID, result_row("toolu_p"))
    a_call("toolu_b")
    assert state.kind_of(SID) is Kind.APPROVAL


def test_a_question_and_a_plan_are_not_permission_windows(tab):
    a_call("toolu_q", "AskUserQuestion", {"questions": []})
    look(screens.question())
    assert state.is_open(SID) is False and tab["pending_permission"] is None


def test_the_window_is_open_since_its_hook_and_is_told_to_the_parent_by_that_time():
    a_call()
    state.open_window(SID, "Bash", LS, "p1", now=100.0)
    assert state.permission_opened_at(SID) is None
    look(screens.approval("ls -la"))
    assert state.permission_opened_at(SID) == 100.0


def test_a_new_turn_of_the_person_forgets_the_calls_of_the_turn_before():
    a_call()
    state.open_window(SID, "Bash", LS, "p1", now=1.0)
    state.fold_row(SID, {"type": "user", "message": {"content": "next please"}})
    assert state.kind_of(SID) is Kind.NONE and state.current_window(SID) is None


def test_close_all_forgets_the_windows_and_the_calls():
    a_call()
    state.open_window(SID, "Bash", LS, "p1", now=1.0)
    state.close_all(SID, "restart")
    assert state.current_window(SID) is None and state.kind_of(SID) is Kind.NONE


def test_after_a_restart_the_table_is_read_again_from_the_turn_of_the_record(tmp_path, monkeypatch):
    """The backend that started after the rows of the turn has not seen them: what the window is comes from the record."""
    record = tmp_path / "conv.jsonl"
    rows = [{"type": "user", "message": {"content": "earlier"}}, call_row("toolu_old", "Bash", LS), result_row("toolu_old"),
            {"type": "user", "message": {"content": "do it"}}, call_row("toolu_1", "Bash", {"command": "rm x"})]
    record.write_text("".join(json.dumps(row) + "\n" for row in rows))
    monkeypatch.setattr(state.jsonl_watcher, "get_jsonl_for", lambda _sid: record)
    assert state.kind_of(SID) is Kind.APPROVAL
    look(screens.approval("rm x"))
    assert state.is_open(SID) and state.current_window(SID).tool_input == {"command": "rm x"}


def test_a_record_that_cannot_be_read_leaves_the_table_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(state.jsonl_watcher, "get_jsonl_for", lambda _sid: tmp_path / "missing.jsonl")
    assert state.kind_of(SID) is Kind.NONE


def test_the_numbers_of_the_windows_grow():
    a_call("toolu_1")
    a_call("toolu_2")
    numbers = [state.open_window(SID, "Bash", LS, "p1", now=1.0).number for _ in range(2)]
    assert numbers == [1, 2]
