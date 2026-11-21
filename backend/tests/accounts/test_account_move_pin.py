"""The operator's move of a tab to another account pins the tab there (`account_pinned`), in the step that writes the
account; the account fallback's own moves do not. The move is claimed, so it does not meet the fallback's."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import backend.terminal.routes as pty_routes
from backend.jsonl import resolver as jsonl_resolver
from backend.accounts.account_move import move_tab_account
from backend.accounts.tab_claim import claimed
from backend.tests.async_run import run as _run
from backend.tests.fork.test_fork import _assistant, _setup_account_move


def test_a_move_by_hand_pins_the_tab_to_the_account_it_was_moved_to(tmp_path, monkeypatch, isolated_state):
    sessions_mod, tab, _src, _work, _events = _setup_account_move(tmp_path, monkeypatch, isolated_state)
    out = _run(sessions_mod.move_session_account(tab.id, {"account_id": "work"}))
    assert (tab.account_id, tab.account_pinned, tab.fallback_from) == ("work", True, None)
    assert out["account_pinned"] is True


def test_a_move_by_the_account_fallback_does_not_pin_the_tab(tmp_path, monkeypatch, isolated_state):
    _sessions, tab, _src, _work, _events = _setup_account_move(tmp_path, monkeypatch, isolated_state)
    _run(move_tab_account(tab.id, "work", fallback_from="personal"))
    assert (tab.account_id, tab.fallback_from, tab.account_pinned) == ("work", "personal", False)


def test_choosing_the_account_the_tab_runs_on_clears_where_it_belongs_and_pins_it(tmp_path, monkeypatch, isolated_state):
    sessions_mod, tab, _src, _work, events = _setup_account_move(tmp_path, monkeypatch, isolated_state)
    tab.account_id, tab.fallback_from = "work", "personal"
    _run(sessions_mod.move_session_account(tab.id, {"account_id": "work"}))
    assert (tab.account_id, tab.fallback_from, tab.account_pinned) == ("work", None, True)
    assert events == []                                       # the conversation was not touched


def test_the_same_account_is_not_pinned_by_a_move_that_is_not_the_operators(tmp_path, monkeypatch, isolated_state):
    _sessions, tab, _src, _work, events = _setup_account_move(tmp_path, monkeypatch, isolated_state)
    tab.account_id, tab.fallback_from = "work", "personal"
    _run(move_tab_account(tab.id, "work"))
    assert (tab.fallback_from, tab.account_pinned, events) == ("personal", False, [])


def test_a_tab_with_no_conversation_yet_is_pinned_where_it_is_moved(tmp_path, monkeypatch, isolated_state):
    sessions_mod, tab, _src, _work, events = _setup_account_move(tmp_path, monkeypatch, isolated_state)
    monkeypatch.setattr(jsonl_resolver, "resolve_jsonl", lambda *_args, **_kwargs: None)
    tab.resume_session_id = None
    _run(sessions_mod.move_session_account(tab.id, {"account_id": "work"}))
    assert (tab.account_id, tab.account_pinned, events) == ("work", True, [])


def test_the_pin_stays_while_it_is_already_set(tmp_path, monkeypatch, isolated_state):
    sessions_mod, tab, _src, _work, _events = _setup_account_move(tmp_path, monkeypatch, isolated_state)
    tab.account_pinned = True
    _run(move_tab_account(tab.id, "work", fallback_from="personal"))
    assert tab.account_pinned is True


def test_a_move_by_hand_is_refused_while_another_feature_has_the_tab(tmp_path, monkeypatch, isolated_state):
    sessions_mod, tab, _src, _work, events = _setup_account_move(tmp_path, monkeypatch, isolated_state)
    with claimed(tab.id) as mine:
        assert mine
        with pytest.raises(HTTPException) as refused:
            _run(sessions_mod.move_session_account(tab.id, {"account_id": "work"}))
    assert refused.value.status_code == 409
    assert (tab.account_id, tab.account_pinned, events) == ("personal", False, [])
    _run(sessions_mod.move_session_account(tab.id, {"account_id": "work"}))          # the claim was let go
    assert tab.account_id == "work"


def test_a_tab_whose_conversation_could_not_be_written_is_not_pinned(tmp_path, monkeypatch, isolated_state):
    lines = [_assistant("a1", None, content=[{"type": "tool_use", "name": "Read", "id": "t1"}])]
    sessions_mod, tab, _src, _work, events = _setup_account_move(tmp_path, monkeypatch, isolated_state, lines)
    with pytest.raises(HTTPException):
        _run(sessions_mod.move_session_account(tab.id, {"account_id": "work"}))
    assert (tab.account_id, tab.account_pinned, events) == ("personal", False, [])


def test_a_tab_that_could_not_be_opened_on_the_new_account_is_pinned_there(tmp_path, monkeypatch, isolated_state):
    sessions_mod, tab, _src, _work, _events = _setup_account_move(tmp_path, monkeypatch, isolated_state)

    async def _fail(_sid, **_kwargs):
        raise RuntimeError("no tmux")
    monkeypatch.setattr(pty_routes, "ensure_pty_session_for", _fail)
    with pytest.raises(HTTPException) as failed:
        _run(sessions_mod.move_session_account(tab.id, {"account_id": "work"}))
    assert failed.value.status_code == 500
    assert (tab.account_id, tab.account_pinned) == ("work", True)
