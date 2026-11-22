"""Which call of the record a window belongs to (`permission_window/window_table.py`)."""
from __future__ import annotations

from backend.permission_window import window_table as table
from backend.tests.permission_window.conftest import call_row, decision_row, result_row


def calls(*pairs):
    return {tool_use_id: table.RecordedCall(tool_use_id, name, tool_input) for tool_use_id, name, tool_input in pairs}


def test_the_call_with_the_same_input_is_the_one():
    found = calls(("a", "Bash", {"command": "ls"}), ("b", "Bash", {"command": "pwd"}))
    assert table.select(found, "Bash", {"command": "pwd"}, frozenset()).tool_use_id == "b"


def test_a_rewritten_input_ties_to_the_oldest_call_of_the_same_tool():
    found = calls(("a", "Read", {"file_path": "/x"}), ("b", "Bash", {"command": "echo 1"}),
                  ("c", "Bash", {"command": "echo 2"}))
    assert table.select(found, "Bash", {"command": "echo rewritten"}, frozenset()).tool_use_id == "b"


def test_a_call_an_earlier_window_took_is_left_out():
    found = calls(("a", "Bash", {"command": "ls"}), ("b", "Bash", {"command": "ls"}))
    assert table.select(found, "Bash", {"command": "ls"}, frozenset({"a"})).tool_use_id == "b"


def test_no_call_of_that_tool_is_none():
    assert table.select(calls(("a", "Read", {})), "Bash", {}, frozenset()) is None


def test_an_assistant_row_adds_its_calls_and_a_result_resolves_one():
    folded = table.CallTable()
    table.apply_effect(folded, table.effect_of_row(call_row("a", "Bash", {"command": "ls"})))
    assert list(folded.open) == ["a"]
    table.apply_effect(folded, table.effect_of_row(result_row("a")))
    assert (list(folded.open), list(folded.resolved)) == ([], ["a"])


def test_a_decision_attachment_resolves_the_call_too():
    folded = table.CallTable()
    table.apply_effect(folded, table.effect_of_row(call_row("a", "Bash", {})))
    table.apply_effect(folded, table.effect_of_row(decision_row("a")))
    assert list(folded.resolved) == ["a"]


def test_a_row_of_the_persons_words_starts_a_new_turn():
    folded = table.CallTable()
    table.apply_effect(folded, table.effect_of_row(call_row("a", "Bash", {})))
    table.apply_effect(folded, table.effect_of_row({"type": "user", "message": {"content": "next please"}}))
    assert (folded.open, folded.resolved) == ({}, {})
