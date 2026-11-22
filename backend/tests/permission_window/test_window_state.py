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


# --- G2: the description is part of the command field -------------------------------------------------------------------

def test_g2_a_hook_input_with_a_description_is_answerable_when_the_dialog_shows_both(tab):
    described = {"command": "ls -la", "description": "List the files"}
    a_call(tool_input=described)
    state.open_window(SID, "Bash", described, "p1", now=1.0)
    look(screens.approval("ls -la", description="List the files"))
    assert tab["pending_permission"]["answerable"] is True


def test_g2_a_dialog_that_shows_more_than_the_hooks_command_is_not_answerable(tab):
    a_call()
    state.open_window(SID, "Bash", LS, "p1", now=1.0)
    look(screens.approval("ls -la", description="and also do this other thing"))
    assert tab["pending_permission"]["answerable"] is False


# --- G8: only the person's words and the mark of an interrupt end a turn ---------------------------------------------------

def test_g8_a_row_the_harness_wrote_does_not_end_the_turn():
    """Red before the fix: any user row that was not a tool result (a skill loaded, a caveat) forgot the open call."""
    a_call()
    for row in ({"type": "user", "isMeta": True, "message": {"content": [{"type": "text", "text": "loaded a skill"}]}},
                {"type": "user", "message": {"content": "<command-name>/model</command-name>"}},
                {"type": "system", "content": "caveat"}):
        state.fold_row(SID, row)
    assert state.kind_of(SID) is Kind.APPROVAL


def test_g8_a_row_of_a_sub_agent_changes_nothing():
    a_call()
    state.fold_row(SID, {**call_row("toolu_s", "Bash", {"command": "x"}), "isSidechain": True})
    state.fold_row(SID, {"type": "user", "isSidechain": True, "message": {"content": "the sub-agent's prompt"}})
    state.fold_row(SID, {**result_row("toolu_1"), "isSidechain": True})
    assert list(state._tab(SID).table.open) == ["toolu_1"]


def test_g8_the_mark_of_an_interrupt_ends_the_turn():
    a_call()
    state.fold_row(SID, {"type": "user", "message": {"content": [{"type": "text", "text": "[Request interrupted by user for tool use]"}]}})
    assert state.kind_of(SID) is Kind.NONE


def test_g8_a_turn_read_again_from_the_record_ends_at_the_same_rows(tmp_path, monkeypatch):
    record = tmp_path / "conv.jsonl"
    rows = [call_row("toolu_old", "Bash", LS), {"type": "user", "message": {"content": "do it"}},
            {"type": "user", "isMeta": True, "message": {"content": [{"type": "text", "text": "skill"}]}},
            call_row("toolu_1", "Bash", {"command": "rm x"})]
    record.write_text("".join(json.dumps(row) + "\n" for row in rows))
    monkeypatch.setattr(state.jsonl_watcher, "get_jsonl_for", lambda _sid: record)
    assert state.kind_of(SID) is Kind.APPROVAL and list(state._tab(SID).table.open) == ["toolu_1"]


# --- G11: a question or a plan the record does not hold yet ----------------------------------------------------------------

@pytest.mark.parametrize("tool, kind", [("AskUserQuestion", Kind.QUESTION), ("ExitPlanMode", Kind.PLAN)])
def test_g11_a_question_or_plan_known_from_its_hook_is_that_kind_before_the_record_has_it(tool, kind):
    """Red before the fix: the window of a question was a window nothing is known of, and its answer was refused."""
    state.note_choice_hook(SID, tool)
    assert state.kind_of(SID) is kind


def test_g11_the_record_decides_once_it_has_the_call():
    state.note_choice_hook(SID, "AskUserQuestion")
    a_call("toolu_b")
    assert state.kind_of(SID) is Kind.APPROVAL


def test_g11_the_hook_is_forgotten_when_the_record_has_the_question_a_turn_ends_or_the_input_box_shows_twice():
    for ending in (lambda: a_call("toolu_q", "AskUserQuestion", {"questions": []}),
                   lambda: state.fold_row(SID, {"type": "user", "message": {"content": "next"}}),
                   lambda: (look(screens.idle()), look(screens.idle())),
                   lambda: state.close_all(SID, "stop")):
        state.note_choice_hook(SID, "AskUserQuestion")
        ending()
        assert state._tab(SID).choice_hook is None


def test_g11_one_look_at_the_input_box_does_not_forget_it():
    state.note_choice_hook(SID, "ExitPlanMode")
    look(screens.idle())
    assert state.kind_of(SID) is Kind.PLAN


# --- G13: the record is read in a thread, and the row that is folded reads nothing -----------------------------------------

def test_g13_folding_a_row_and_the_detectors_look_read_no_record(monkeypatch):
    def reading(*_args):
        raise AssertionError("a record was read on the caller's thread")
    monkeypatch.setattr(state, "_rows_of_turn", reading)
    monkeypatch.setattr(state.jsonl_watcher, "get_jsonl_for", lambda _sid: "a-record")
    a_call()
    state.open_window(SID, "Bash", LS, "p1", now=1.0)
    state.note_screen(SID, read_screen(screens.approval("ls -la")))


def test_g13_the_table_is_read_in_a_thread_by_prepare_and_the_detectors_look(tmp_path, monkeypatch):
    import asyncio
    import threading
    record = tmp_path / "conv.jsonl"
    record.write_text(json.dumps(call_row("toolu_1", "Bash", LS)) + "\n")
    threads = []
    real = state._rows_of_turn
    monkeypatch.setattr(state, "_rows_of_turn", lambda path: threads.append(threading.current_thread()) or real(path))
    monkeypatch.setattr(state.jsonl_watcher, "get_jsonl_for", lambda _sid: record)

    async def scenario():
        main = threading.current_thread()
        await state.look(SID, read_screen(screens.approval("ls -la")))
        return main
    main = asyncio.run(scenario())
    assert len(threads) == 1 and threads[0] is not main
    assert state.is_open(SID) and state.current_window(SID).tool_input == LS


def test_g13_the_rows_folded_while_the_record_is_read_are_kept_and_a_new_turn_wins(tmp_path, monkeypatch):
    record = tmp_path / "conv.jsonl"
    record.write_text(json.dumps(call_row("toolu_old", "Bash", LS)) + "\n")
    real = state._rows_of_turn

    def reading_while_rows_come(path):
        rows = real(path)
        state.fold_row(SID, call_row("toolu_new", "Bash", {"command": "pwd"}))     # written after the read
        return rows
    monkeypatch.setattr(state, "_rows_of_turn", reading_while_rows_come)
    monkeypatch.setattr(state.jsonl_watcher, "get_jsonl_for", lambda _sid: record)
    assert state.kind_of(SID) is Kind.APPROVAL and list(state._tab(SID).table.open) == ["toolu_old", "toolu_new"]

    state.close_all(SID, "test")
    state._tabs.clear()

    def a_turn_begins_meanwhile(path):
        rows = real(path)
        state.fold_row(SID, {"type": "user", "message": {"content": "a new request"}})
        state.fold_row(SID, call_row("toolu_new", "Bash", {"command": "pwd"}))
        return rows
    monkeypatch.setattr(state, "_rows_of_turn", a_turn_begins_meanwhile)
    state.kind_of(SID)
    assert list(state._tab(SID).table.open) == ["toolu_new"]


# --- G12: one push for each window, when the screen first shows it ---------------------------------------------------------

def test_g12_a_window_is_taken_for_a_push_once_when_the_screen_shows_it():
    a_call()
    state.open_window(SID, "Bash", LS, "p1", now=1.0)
    assert state.take_unpushed(SID) is None                  # the hook alone shows no window
    look(screens.approval("ls -la"))
    shown = state.take_unpushed(SID)
    assert shown is not None and shown.tool_name == "Bash"
    look(screens.approval("ls -la"))
    assert state.take_unpushed(SID) is None


def test_g12_the_next_window_of_a_row_is_a_push_of_its_own():
    a_call("toolu_1", tool_input={"command": "ls"})
    a_call("toolu_2", tool_input={"command": "pwd"})
    first = state.open_window(SID, "Bash", {"command": "ls"}, "p1", now=1.0)
    state.open_window(SID, "Bash", {"command": "pwd"}, "p1", now=1.0)
    look(screens.approval("ls"))
    assert state.take_unpushed(SID).number == first.number
    state.note_answered(SID, first.number, read_screen(screens.approval("ls")).fingerprint)
    look(screens.approval("pwd"))
    assert state.take_unpushed(SID).tool_input == {"command": "pwd"}


# --- G14: no pane, no screen -------------------------------------------------------------------------------------------------

def test_g14_the_window_is_gone_with_the_pane():
    a_call()
    state.open_window(SID, "Bash", LS, "p1", now=1.0)
    look(screens.approval("ls -la"))
    assert state.is_open(SID)
    state.forget_screen(SID)
    assert state.is_open(SID) is False and state.permission_opened_at(SID) is None and state.current_window(SID) is None


def test_g14_closing_the_tabs_windows_forgets_the_last_look_too(tab):
    a_call()
    state.open_window(SID, "Bash", LS, "p1", now=1.0)
    look(screens.approval("ls -la"))
    state.close_all(SID, "restart")
    assert state.is_open(SID) is False and tab["pending_permission"] is None and state.input_looks(SID) == 0


# --- G7: the mark that an answer was typed is made with the key ------------------------------------------------------------

def test_g7_the_mark_of_a_typed_answer_is_made_before_the_rest_of_the_bookkeeping():
    a_call()
    window = state.open_window(SID, "Bash", LS, "p1", now=1.0)
    reading = read_screen(screens.approval("ls -la"))
    look(screens.approval("ls -la"))
    assert state.situation(SID, reading).answerable
    state.mark_answer_typed(SID, reading.fingerprint)
    assert state.situation(SID, reading).answerable is False and state.current_window(SID) is window
