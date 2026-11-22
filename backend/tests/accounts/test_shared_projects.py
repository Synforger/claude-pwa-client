"""Moving a tab between two accounts that keep their records in one folder: the same conversation is reopened under the
other account (same id, no new file, nothing recorded to delete), and a conversation that cannot be reopened as it is
is written as a new session next to its source (`accounts/account_move.py`, `accounts/shared_reopen.py`)."""
from __future__ import annotations

import time

import pytest
from fastapi import HTTPException

import backend.accounts.tab_restart as tab_restart
from backend._common.state import SleepMark
from backend.accounts.account_move import move_tab_account
from backend.fork.lineage import LineageCut
from backend.tests.accounts.conftest import CLAUDE_ID, uuids_of, write_record
from backend.tests.async_run import run as _run
from backend.tests.fork.test_fork import SAMPLE
from backend.tests.limit_samples import lines_of, message_row, stopped_mid_turn, tool_call, use_accounts


def _records(shared) -> list[str]:
    return sorted(path.name for path in shared.folder.glob("*.jsonl"))


def test_a_running_tab_reopens_the_same_conversation_under_the_other_account(shared):
    tab = shared.tab
    _run(move_tab_account(tab.id, "work", fallback_from="personal", at_break=True))
    assert (tab.account_id, tab.fallback_from, tab.resume_session_id) == ("work", "personal", CLAUDE_ID)
    assert tab.fallback_copy is None
    assert _records(shared) == [f"{CLAUDE_ID}.jsonl"]
    assert shared.events == [f"kill {tab.id}", f"spawn {tab.id}"]
    assert shared.ended == [(tab.id, str(shared.record))]


def test_a_sleeping_tab_reopens_the_conversation_its_mark_names(shared):
    tab = shared.tab
    tab.sleep = SleepMark(claude_sid=CLAUDE_ID, record=str(shared.record), slept_at=int(time.time()),
                          account_id="personal")
    _run(move_tab_account(tab.id, "work", fallback_from="personal"))
    assert (tab.account_id, tab.resume_session_id, tab.fallback_copy) == ("work", CLAUDE_ID, None)
    assert tab.sleep is None                       # a mark that is still valid would be read before the id chosen here
    assert _records(shared) == [f"{CLAUDE_ID}.jsonl"]


def test_a_sleeping_tab_whose_account_changed_still_reopens_the_conversation_of_the_shared_folder(shared):
    tab = shared.tab
    tab.sleep = SleepMark(claude_sid=CLAUDE_ID, record=str(shared.record), slept_at=1, account_id="personal")
    tab.account_id = "work"
    assert tab.sleeping_claude_sid() == CLAUDE_ID


def test_a_tab_a_usage_limit_stopped_reopens_with_the_tool_results_of_its_turn(shared):
    write_record(shared.record, lines_of(stopped_mid_turn()))
    _run(move_tab_account(shared.tab.id, "work", cut=LineageCut.THROUGH_TOOL_RESULTS, fallback_from="personal",
                          at_break=True))
    assert (shared.tab.resume_session_id, shared.tab.fallback_copy) == (CLAUDE_ID, None)
    assert _records(shared) == [f"{CLAUDE_ID}.jsonl"]


@pytest.mark.parametrize("why", ["a call with no answer", "a line not finished", "a turn still going"])
def test_a_conversation_that_cannot_be_reopened_as_it_is_is_written_as_a_new_session_in_the_same_folder(shared, why):
    if why == "a call with no answer":
        write_record(shared.record, lines_of([message_row("u1", None, "user", "hi"),
                                              message_row("a1", "u1", "assistant", "hello"),
                                              message_row("u2", "a1", "user", "read it"), tool_call("a2", "u2")]))
    elif why == "a line not finished":
        write_record(shared.record, [*SAMPLE, '{"type": "user", "uu'], whole_line_end=False)
    else:
        write_record(shared.record, [*SAMPLE, *lines_of([message_row("u3", "a2", "user", "go on"),
                                                         tool_call("a3", "u3")])])
    tab = shared.tab
    _run(move_tab_account(tab.id, "work", fallback_from="personal", at_break=True))
    new_id = tab.resume_session_id
    assert new_id and new_id != CLAUDE_ID
    assert _records(shared) == sorted([f"{CLAUDE_ID}.jsonl", f"{new_id}.jsonl"])
    assert tab.fallback_copy is None                # nothing was written for another account: nothing to delete
    assert shared.record.is_file()                  # the record the tab came from stays


def test_a_move_by_hand_of_a_running_tab_writes_a_new_session_in_the_same_folder(shared):
    """The operator's move has not found the tab at a break, so the conversation is cut as before."""
    tab = shared.tab
    _run(move_tab_account(tab.id, "work", pin=True))
    assert tab.resume_session_id != CLAUDE_ID
    assert uuids_of(shared.folder / f"{tab.resume_session_id}.jsonl") == ["u1", "a1", "u2", "a2"]
    assert (tab.account_pinned, tab.fallback_copy) == (True, None)
    assert shared.record.is_file()


def test_a_record_written_before_the_accounts_shared_is_taken_off_the_tab_and_kept(shared):
    tab = shared.tab
    tab.account_id = "work"
    tab.fallback_from = "personal"
    tab.fallback_copy = str(shared.work_projects / shared.folder.name / f"{CLAUDE_ID}.jsonl")
    _run(move_tab_account(tab.id, "personal", at_break=True))
    assert tab.fallback_copy is None
    assert shared.record.is_file()                  # it is the tab's own conversation: never deleted
    assert tab.resume_session_id == CLAUDE_ID


@pytest.mark.parametrize("raises", [False, True])
@pytest.mark.parametrize("reopened", [True, False])
def test_a_tab_whose_claude_could_not_be_stopped_is_not_moved(shared, monkeypatch, raises, reopened):
    async def not_stopped(_sid):
        if raises:
            raise OSError("no tmux")
        return False
    monkeypatch.setattr(tab_restart, "stop_tab", not_stopped)
    tab = shared.tab
    with pytest.raises(HTTPException) as refused:
        _run(move_tab_account(tab.id, "work", fallback_from="personal", pin=True, at_break=reopened))
    assert (refused.value.status_code, refused.value.detail["code"]) == (409, "tab_not_stopped")
    assert (tab.account_id, tab.account_pinned, tab.fallback_from, tab.resume_session_id) == (
        "personal", False, None, None)
    assert _records(shared) == [f"{CLAUDE_ID}.jsonl"]           # a session written for the move goes again
    assert shared.ended == [] and shared.events == []


def test_a_failure_to_write_the_new_session_pins_nothing(shared, monkeypatch):
    """The tab's record has no cut to carry the conversation from: the move is refused before the tab is pinned."""
    write_record(shared.record, lines_of([tool_call("a1", None)]))
    with pytest.raises(HTTPException):
        _run(move_tab_account(shared.tab.id, "work", pin=True))
    assert (shared.tab.account_id, shared.tab.account_pinned) == ("personal", False)
    assert shared.events == []


def test_a_new_session_for_the_other_account_goes_next_to_its_source_and_is_not_marked_as_moved(shared):
    from backend.fork.lineage import write_lineage  # noqa: PLC0415
    written = write_lineage(shared.tab.id, None, "work")
    assert (written.moved, written.path.parent) == (False, shared.folder)
    assert uuids_of(written.path) == ["u1", "a1", "u2", "a2"]


@pytest.mark.parametrize("spelling", ["personal", "work"])
def test_a_record_in_a_folder_two_accounts_share_is_never_deleted(shared, spelling):
    from backend.accounts.account_move import remove_written_copy  # noqa: PLC0415
    root = shared.projects if spelling == "personal" else shared.work_projects
    assert remove_written_copy(str(root / shared.folder.name / f"{CLAUDE_ID}.jsonl")) is False
    assert shared.record.is_file()


def test_a_record_in_a_folder_of_one_account_is_still_deleted(shared, monkeypatch):
    from backend.accounts.account_move import remove_written_copy  # noqa: PLC0415
    use_accounts(monkeypatch, {"personal": {"display_name": "Personal", "env": {}}})
    assert remove_written_copy(str(shared.record)) is True
    assert not shared.record.exists()
