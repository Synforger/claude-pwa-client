"""Pinning a tab to its account: the mark is set and cleared where the tab's name and notifications are, and it is
kept with the tab's definition (`routes/sessions.py`, `_common/state.py`)."""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from backend._common import state as state_mod


@pytest.fixture
def sessions_mod():
    """The sessions route, imported when a test runs: it reads the agents of the configuration when it is first imported,
    and the suite's configuration is put in place only once a test has started."""
    import backend.routes.sessions as module  # noqa: PLC0415
    return module


@pytest.fixture
def tab(isolated_state):
    return isolated_state.register_session("agent_a", title="T")


def test_a_new_tab_is_not_pinned(tab, sessions_mod):
    assert tab.account_pinned is False and sessions_mod.session_row(tab)["account_pinned"] is False


def test_the_mark_is_set_and_cleared_through_the_same_door_as_the_name_and_the_notifications(tab, sessions_mod):
    row = sessions_mod.patch_session(tab.id, {"account_pinned": True})
    assert row["account_pinned"] is True and tab.account_pinned is True
    row = sessions_mod.patch_session(tab.id, {"account_pinned": False})
    assert row["account_pinned"] is False and tab.account_pinned is False


def test_the_mark_can_be_set_together_with_the_other_fields_which_stay_as_they_were(tab, sessions_mod):
    sessions_mod.patch_session(tab.id, {"account_pinned": True, "title": "Named"})
    assert (tab.title, tab.notify_mode, tab.account_pinned) == ("Named", "both", True)
    sessions_mod.patch_session(tab.id, {"notify_mode": "off"})
    assert tab.account_pinned is True                               # a change of another field leaves the mark


@pytest.mark.parametrize("value", ["yes", 1, 0, []])
def test_a_value_that_is_not_true_or_false_is_refused_and_nothing_changes(tab, sessions_mod, value):
    with pytest.raises(HTTPException) as refused:
        sessions_mod.patch_session(tab.id, {"account_pinned": value})
    assert refused.value.status_code == 400 and tab.account_pinned is False


def test_a_patch_with_nothing_to_change_is_still_refused(tab, sessions_mod):
    with pytest.raises(HTTPException) as refused:
        sessions_mod.patch_session(tab.id, {})
    assert refused.value.status_code == 400


def test_the_mark_is_kept_across_a_restart_of_the_backend(tab, sessions_mod):
    sessions_mod.patch_session(tab.id, {"account_pinned": True})
    assert json.loads(state_mod.SESSION_META_PATH.read_text())[0]["account_pinned"] is True
    state_mod.sessions_meta.clear()
    state_mod.sessions_meta.update(state_mod._load_sessions_meta())
    assert state_mod.sessions_meta[tab.id].account_pinned is True
