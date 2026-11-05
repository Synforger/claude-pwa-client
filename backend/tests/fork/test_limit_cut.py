"""The cut that carries the tool results of a turn a usage limit stopped and leaves the limit's row out
(`fork/fork.py`, `fork/lineage.py`)."""
from __future__ import annotations

import json

from backend.fork.fork import is_limit_stop_row, latest_clean_fork_point, latest_cut_through_tool_results
from backend.fork.lineage import LineageCut, write_lineage
from backend.tests.fork.test_fork import _setup_account_move
from backend.tests.limit_samples import (limit_stop_row, lines_of, message_row, stopped_mid_turn, tool_call,
                                         tool_result)


def _uuids(lines: list[str]) -> list[str]:
    return [json.loads(line)["uuid"] for line in lines if line.strip()]


def test_only_a_usage_limit_row_is_a_limit_stop():
    assert is_limit_stop_row(limit_stop_row("x", None))
    assert not is_limit_stop_row(limit_stop_row("x", None, error="authentication_failed"))
    assert not is_limit_stop_row(limit_stop_row("x", None, apiErrorIsTransient=True))
    assert not is_limit_stop_row(message_row("x", None, "assistant", "hello"))


def test_the_cut_through_tool_results_keeps_the_result_and_drops_the_limit_row():
    lines = lines_of(stopped_mid_turn())
    assert latest_cut_through_tool_results(lines) == "u2"
    # the default cut counts the limit's own row as a finished answer, and would carry it
    assert latest_clean_fork_point(lines) == "lim1"


def test_a_conversation_ending_in_a_tool_call_falls_back_to_the_clean_point_without_the_limit_row():
    # the latest clean point is the prompt before the call: the call has no result to keep
    rows = [message_row("u1", None, "user", "go"), message_row("a1", "u1", "assistant", "text"),
            message_row("u2", "a1", "user", "more"), tool_call("a2", "u2"), limit_stop_row("lim1", "a2")]
    assert latest_cut_through_tool_results(lines_of(rows)) == "u2"


def test_writing_a_stopped_conversation_keeps_its_tool_results_and_leaves_the_limit_row_out(
        tmp_path, monkeypatch, isolated_state):
    """The sample is a record in the shape a real one has: the move carries the turn up to its last tool result."""
    sessions_mod, tab, src, work_dir, _events = _setup_account_move(
        tmp_path, monkeypatch, isolated_state, lines_of(stopped_mid_turn()))
    written = write_lineage(tab.id, None, "work", cut=LineageCut.THROUGH_TOOL_RESULTS)
    assert written.moved is True
    assert written.path.parent == work_dir
    carried = written.path.read_text().splitlines()
    assert _uuids(carried) == ["u1", "a1", "u2"]
    assert not any(json.loads(line).get("isApiErrorMessage") for line in carried)
    assert all(json.loads(line)["sessionId"] == written.claude_id for line in carried)
    assert _uuids(src.read_text().splitlines()) == ["u1", "a1", "u2", "lim1"]      # the source is untouched


def test_the_default_cut_is_unchanged(tmp_path, monkeypatch, isolated_state):
    rows = [message_row("u1", None, "user", "go"), message_row("a1", "u1", "assistant", "done"),
            message_row("u2", "a1", "user", "next"), tool_call("a2", "u2"), tool_result("u3", "a2", "a2")]
    _sessions, tab, _src, _work, _events = _setup_account_move(tmp_path, monkeypatch, isolated_state, lines_of(rows))
    written = write_lineage(tab.id, None, "work")
    assert _uuids(written.path.read_text().splitlines()) == ["u1", "a1", "u2"]
