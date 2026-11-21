"""A tab's own folder of the list (`list_folder`): set when the tab is made or later, kept with the tab, and refused
when it is not `<agent id>/<folder>/...` (`routes/sessions.py`, `_common/state.py`, `_common/list_folder.py`)."""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException

from backend._common.list_folder import parse_list_folder


@pytest.fixture
def sessions_mod(monkeypatch):
    """The sessions route, imported when a test runs (it reads the agents of the configuration on import), with the
    spawn of a new tab's terminal left out."""
    import backend.routes.sessions as module  # noqa: PLC0415
    import backend.terminal.routes as terminal_routes  # noqa: PLC0415

    async def no_spawn(_sid: str) -> None:
        return None

    monkeypatch.setattr(terminal_routes, "ensure_pty_session_for", no_spawn)
    return module


@pytest.fixture
def tab(isolated_state):
    return isolated_state.register_session("agent_a", title="T")


def test_the_folder_is_trimmed_and_needs_a_folder_below_the_agent():
    assert parse_list_folder(" agent_a / Game / World A ") == "agent_a/Game/World A"
    for bad in ("agent_a", "agent_a//World", " / ", "", None, 42, ["agent_a", "Game"]):
        assert parse_list_folder(bad) is None


def test_a_tab_made_with_a_folder_carries_it_in_its_row(isolated_state, sessions_mod):
    row = asyncio.run(sessions_mod.create_session({"agent_id": "agent_a", "title": "W", "list_folder": "agent_a/Game/W"}))
    assert row["list_folder"] == "agent_a/Game/W"
    assert isolated_state.sessions_meta[row["id"]].list_folder == "agent_a/Game/W"


def test_a_tab_made_without_a_folder_is_placed_by_its_agent(isolated_state, sessions_mod):
    row = asyncio.run(sessions_mod.create_session({"agent_id": "agent_a", "title": "W"}))
    assert row["list_folder"] is None


def test_a_bad_folder_makes_no_tab(isolated_state, sessions_mod):
    before = set(isolated_state.sessions_meta)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(sessions_mod.create_session({"agent_id": "agent_a", "list_folder": "agent_a"}))
    assert caught.value.status_code == 400 and caught.value.detail["code"] == "invalid_list_folder"
    assert set(isolated_state.sessions_meta) == before


def test_the_folder_is_moved_and_cleared_through_the_same_door_as_the_name(tab, sessions_mod):
    assert sessions_mod.patch_session(tab.id, {"list_folder": "agent_a/Game/W"})["list_folder"] == "agent_a/Game/W"
    assert sessions_mod.patch_session(tab.id, {"list_folder": None})["list_folder"] is None
    sessions_mod.patch_session(tab.id, {"list_folder": "agent_a/Game/W"})
    assert sessions_mod.patch_session(tab.id, {"list_folder": ""})["list_folder"] is None


def test_a_bad_folder_leaves_the_tab_as_it_was(tab, sessions_mod):
    with pytest.raises(HTTPException) as caught:
        sessions_mod.patch_session(tab.id, {"title": "Renamed", "list_folder": "agent_a//W"})
    assert caught.value.detail["code"] == "invalid_list_folder"
    assert tab.title == "T" and tab.list_folder is None


def test_the_folder_survives_a_restart_of_the_backend(tab, sessions_mod, isolated_state):
    sessions_mod.patch_session(tab.id, {"list_folder": "agent_a/Game/W"})
    saved = json.loads(isolated_state.SESSION_META_PATH.read_text(encoding="utf-8"))
    assert [entry.get("list_folder") for entry in saved if entry["id"] == tab.id] == ["agent_a/Game/W"]
    assert isolated_state._load_sessions_meta()[tab.id].list_folder == "agent_a/Game/W"
