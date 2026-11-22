"""The windows of a tab (`permission_window/window_state.py`): tied to the record, shown to the screen, closed."""
from __future__ import annotations

from backend.permission_window import window_state as state
from backend.tests.permission_window.conftest import SID, call_row, decision_row, result_row

LS = {"command": "ls", "description": "list"}


def test_a_window_tied_to_the_call_with_the_same_input_is_shown_with_the_contract_fields(tab):
    state.fold_row(SID, call_row("toolu_1", "Bash", LS))
    state.open_window(SID, "Bash", LS, "p1", now=100.0)
    assert tab["pending_permission"] == {
        "number": 1, "tool_use_id": "toolu_1", "tool_name": "Bash", "input": LS, "record_input": None,
        "index": 1, "count": 1, "opened_at": 100.0}


def test_an_input_a_guard_rewrote_shows_both(tab):
    state.fold_row(SID, call_row("toolu_1", "Bash", {"command": "ls"}))
    state.open_window(SID, "Bash", {"command": "ls -la"}, "p1", now=1.0)
    shown = tab["pending_permission"]
    assert (shown["tool_use_id"], shown["input"], shown["record_input"]) == (
        "toolu_1", {"command": "ls -la"}, {"command": "ls"})


def test_a_hook_before_its_row_is_tied_when_the_row_comes(tab):
    state.open_window(SID, "Bash", LS, "p1", now=1.0)
    assert tab["pending_permission"]["tool_use_id"] is None
    state.fold_row(SID, call_row("toolu_1", "Bash", LS))
    assert tab["pending_permission"]["tool_use_id"] == "toolu_1"


def test_two_windows_in_a_row_come_one_at_a_time_in_the_order_of_the_calls(tab):
    state.fold_row(SID, call_row("toolu_1", "Bash", {"command": "echo B1"}))
    state.fold_row(SID, call_row("toolu_2", "Bash", {"command": "echo B2"}))
    state.open_window(SID, "Bash", {"command": "echo B2"}, "p1", now=1.0)      # the hooks may arrive in any order
    state.open_window(SID, "Bash", {"command": "echo B1"}, "p1", now=1.1)
    first = tab["pending_permission"]
    assert (first["tool_use_id"], first["index"], first["count"]) == ("toolu_1", 1, 2)
    state.note_answered(SID, first["number"])
    second = tab["pending_permission"]
    assert (second["tool_use_id"], second["index"], second["count"]) == ("toolu_2", 2, 2)
    state.note_answered(SID, second["number"])
    assert tab["pending_permission"] is None


def test_the_number_grows_with_each_window(tab):
    state.open_window(SID, "Bash", {"command": "a"})
    state.close_all(SID, "test")
    state.open_window(SID, "Bash", {"command": "b"})
    assert tab["pending_permission"]["number"] == 2


def test_the_result_row_closes_the_window(tab):
    state.fold_row(SID, call_row("toolu_1", "Bash", LS))
    state.open_window(SID, "Bash", LS, now=1.0)
    state.fold_row(SID, result_row("toolu_1"))
    assert (tab["pending_permission"], state.is_open(SID)) == (None, False)


def test_a_decision_row_closes_it_too(tab):
    state.fold_row(SID, call_row("toolu_1", "Bash", LS))
    state.open_window(SID, "Bash", LS, now=1.0)
    state.fold_row(SID, decision_row("toolu_1"))
    assert state.is_open(SID) is False


def test_a_hook_that_comes_after_the_result_stands_no_window(tab):
    """A gate refused the call 18 ms after it was asked: the result is in the record before the hook arrives."""
    state.fold_row(SID, call_row("toolu_1", "Bash", LS))
    state.fold_row(SID, decision_row("toolu_1"))
    assert state.open_window(SID, "Bash", LS, now=1.0) is None
    assert tab["pending_permission"] is None


def test_the_same_command_asked_again_gets_its_own_window(tab):
    state.fold_row(SID, call_row("toolu_1", "Bash", LS))
    state.open_window(SID, "Bash", LS, now=1.0)
    state.fold_row(SID, result_row("toolu_1"))
    state.fold_row(SID, call_row("toolu_2", "Bash", LS))
    assert state.open_window(SID, "Bash", LS, now=2.0).tool_use_id == "toolu_2"


def test_a_window_seen_and_then_missing_on_two_looks_in_a_row_closes(tab):
    state.open_window(SID, "Bash", LS, now=1.0)
    state.note_screen(SID, True)
    state.note_screen(SID, False)
    assert state.is_open(SID)
    state.note_screen(SID, False)
    assert state.is_open(SID) is False


def test_a_look_that_sees_it_again_starts_the_count_over(tab):
    state.open_window(SID, "Bash", LS, now=1.0)
    state.note_screen(SID, True)
    state.note_screen(SID, False)
    state.note_screen(SID, True)
    state.note_screen(SID, False)
    assert state.is_open(SID)


def test_a_window_not_yet_on_the_pane_is_not_closed_by_looks_that_miss_it(tab):
    """The hook comes some seconds before the pane draws the window."""
    state.open_window(SID, "Bash", LS, now=1.0)
    for _ in range(5):
        state.note_screen(SID, False)
    assert state.is_open(SID)


def test_the_next_window_waits_for_its_own_screen_after_the_first_closes(tab):
    state.fold_row(SID, call_row("toolu_1", "Bash", {"command": "a"}))
    state.fold_row(SID, call_row("toolu_2", "Bash", {"command": "b"}))
    state.open_window(SID, "Bash", {"command": "a"}, now=1.0)
    state.open_window(SID, "Bash", {"command": "b"}, now=1.0)
    state.note_screen(SID, True)
    state.note_screen(SID, False)
    state.note_screen(SID, False)                  # the first is gone
    for _ in range(4):
        state.note_screen(SID, False)              # the pane has not drawn the second yet
    assert tab["pending_permission"]["tool_use_id"] == "toolu_2"


def test_a_session_start_a_stop_or_a_restart_closes_everything(tab):
    state.fold_row(SID, call_row("toolu_1", "Bash", LS))
    state.open_window(SID, "Bash", LS, now=1.0)
    state.close_all(SID, "stop")
    assert (state.is_open(SID), state.is_holding(SID), tab["pending_permission"]) == (False, False, None)
    assert state.open_window(SID, "Bash", LS, now=2.0).tool_use_id is None      # the table of the turn went too


def test_a_question_and_a_plan_approval_are_kept_but_not_shown_as_a_permission(tab):
    state.fold_row(SID, call_row("toolu_9", "AskUserQuestion", {"questions": []}))
    window = state.open_window(SID, "AskUserQuestion", {"questions": []}, now=1.0)
    assert window.is_permission is False
    assert (state.is_open(SID), state.is_holding(SID), tab["pending_permission"]) == (False, True, None)
    state.fold_row(SID, result_row("toolu_9"))
    assert state.is_holding(SID) is False


def test_a_pending_plan_holds_too(tab):
    tab["pending_plan"] = {"tool_use_id": "toolu_p", "plan": "x", "choices": []}
    assert state.is_holding(SID) and not state.is_open(SID)


def test_a_close_is_told_to_the_listeners_and_a_new_turn_forgets_the_calls(tab):
    told = []
    state.add_close_listener(told.append)
    state.fold_row(SID, call_row("toolu_1", "Bash", LS))
    state.open_window(SID, "Bash", LS, now=1.0)
    state.fold_row(SID, result_row("toolu_1"))
    assert told == [SID]
    state.fold_row(SID, call_row("toolu_2", "Bash", LS))
    state.fold_row(SID, {"type": "user", "message": {"content": "hello"}})
    assert state.open_window(SID, "Bash", LS, now=2.0).tool_use_id is None


def test_the_oldest_open_time_is_what_the_child_watch_reads(tab):
    state.open_window(SID, "Bash", {"command": "a"}, now=50.0)
    state.open_window(SID, "Bash", {"command": "b"}, now=80.0)
    assert state.permission_opened_at(SID) == 50.0
