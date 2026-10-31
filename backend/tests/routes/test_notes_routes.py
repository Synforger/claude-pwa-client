"""The memo routes (= GET / PUT /sessions/{sid}/note) and where a tab's memo lives.

A memo is `<tier folder>/pages/<tab id>/memo.md`: the tab's agent writes it at the path in `PWA_NOTE`, the
screen reads and writes the same file through the routes. The read also names the tab's top page (= `index.html`
next to the memo; how it is made is in `test_tab_page.py`).
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from backend._generated import http_endpoints as http
from backend._common.config import FILE_SIZE_LIMIT
from backend.terminal.runner import tmux_session_env_args
from backend.terminal.tab_memo import memo_file, memo_path


async def _stopped(_sid):
    """The tab's claude is gone (= what `stop_tab` reports when it ended)."""
    return True


@pytest.fixture
def tabs(agent_folder, monkeypatch, isolated_state):
    """Two tabs of the test agent, whose folder is `agent_folder`."""
    monkeypatch.setattr(isolated_state, "save_sessions_meta", lambda: None)
    return isolated_state.register_session("agent_a", title="A"), isolated_state.register_session("agent_a", title="B")


@pytest.fixture
def client(tabs):
    # The memo routes load the tab routes, which hold the config as it is when they are loaded: load them after
    # the test's config is in place.
    import backend.routes.notes as notes  # noqa: PLC0415
    app = FastAPI()
    app.include_router(notes.router)
    return TestClient(app)


def started_in(monkeypatch, tab, tier):
    """The agent of `tab` was started in `tier`."""
    tab.tier = tier


def test_a_tab_without_a_memo_reads_empty_and_nothing_is_created(client, tabs, agent_folder):
    a, _ = tabs
    path = agent_folder / "pages" / a.id / "memo.md"
    assert client.get(f"/sessions/{a.id}/note").json() == {"path": str(path), "content": "", "page": None}
    assert not (agent_folder / "pages").exists()


def test_put_writes_the_memo_of_that_tab_only(client, tabs, agent_folder):
    a, b = tabs
    body = client.put(f"/sessions/{a.id}/note", json={"content": "# 設計\n- 6 行で止める\n"}).json()
    assert body == {"path": str(memo_path(a.id)), "content": "# 設計\n- 6 行で止める\n"}
    assert memo_path(a.id).read_text(encoding="utf-8") == "# 設計\n- 6 行で止める\n"
    assert client.get(f"/sessions/{b.id}/note").json()["content"] == ""
    assert not memo_path(b.id).exists()


def test_what_the_agent_wrote_is_what_the_screen_reads(client, tabs):
    a, _ = tabs
    memo_path(a.id).parent.mkdir(parents=True)
    memo_path(a.id).write_text("エージェントが抜き出した文\n", encoding="utf-8")
    assert client.get(f"/sessions/{a.id}/note").json()["content"] == "エージェントが抜き出した文\n"


def test_a_tab_started_in_a_tier_has_its_memo_in_that_tier_folder(client, tabs, agent_folder, monkeypatch):
    a, b = tabs
    (agent_folder / "projects" / "alpha").mkdir(parents=True)
    started_in(monkeypatch, a, "projects/alpha")
    started_in(monkeypatch, b, "normal")
    assert memo_path(a.id) == agent_folder / "projects" / "alpha" / "pages" / a.id / "memo.md"
    assert memo_path(b.id) == agent_folder / "pages" / b.id / "memo.md"
    client.put(f"/sessions/{a.id}/note", json={"content": "x"})
    assert (agent_folder / "projects" / "alpha" / "pages" / a.id / "memo.md").read_text(encoding="utf-8") == "x"


@pytest.mark.parametrize("tier", [None, "projects/not-a-folder"])
def test_a_tier_that_is_unknown_or_has_no_folder_places_the_memo_like_normal(tabs, agent_folder, monkeypatch, tier):
    a, _ = tabs
    started_in(monkeypatch, a, tier)
    assert memo_path(a.id) == agent_folder / "pages" / a.id / "memo.md"


def test_emptying_a_memo_removes_the_file_and_leaves_the_tabs_other_pages(client, tabs):
    a, _ = tabs
    client.put(f"/sessions/{a.id}/note", json={"content": "x"})
    top_page = memo_path(a.id).parent / "index.html"
    top_page.write_text("<html></html>", encoding="utf-8")
    assert client.put(f"/sessions/{a.id}/note", json={"content": ""}).json()["content"] == ""
    assert not memo_path(a.id).exists()
    assert top_page.is_file()
    # A memo that is not there can be emptied too
    assert client.put(f"/sessions/{a.id}/note", json={"content": ""}).status_code == 200


def test_an_unknown_tab_is_not_found(client, agent_folder):
    assert client.get("/sessions/ses_nope/note").status_code == 404
    assert client.put("/sessions/ses_nope/note", json={"content": "x"}).status_code == 404
    assert not (agent_folder / "pages").exists()


def test_a_memo_over_the_size_limit_is_refused_both_ways(client, tabs):
    a, _ = tabs
    assert client.put(f"/sessions/{a.id}/note", json={"content": "x" * (FILE_SIZE_LIMIT + 1)}).status_code == 413
    assert not memo_path(a.id).exists()
    memo_path(a.id).parent.mkdir(parents=True)
    memo_path(a.id).write_text("x" * (FILE_SIZE_LIMIT + 1), encoding="utf-8")
    assert client.get(f"/sessions/{a.id}/note").status_code == 413


def test_responses_match_the_contract(client, tabs):
    a, _ = tabs
    http.PutSessionsSidNoteRequest.model_validate({"content": "x"})
    http.PutSessionsSidNoteResponse.model_validate(client.put(f"/sessions/{a.id}/note", json={"content": "x"}).json())
    http.GetSessionsSidNoteResponse.model_validate(client.get(f"/sessions/{a.id}/note").json())


@pytest.mark.parametrize("bad", ["", "../x", "a/b", "/abs"])
def test_a_memo_file_refuses_what_is_not_an_id(tmp_path, bad):
    with pytest.raises(ValueError):
        memo_file(tmp_path, bad)


def test_an_unknown_tab_has_no_memo_path(agent_folder):
    with pytest.raises(ValueError):
        memo_path("ses_nope")


def test_deleting_the_tab_keeps_its_memo(client, tabs, monkeypatch):
    import backend.routes.sessions as sessions_routes  # noqa: PLC0415
    monkeypatch.setattr(sessions_routes, "stop_tab", _stopped)
    a, b = tabs
    client.put(f"/sessions/{a.id}/note", json={"content": "a"})
    client.put(f"/sessions/{b.id}/note", json={"content": "b"})
    deleted = memo_path(a.id)
    # Its own loop: the shared one may have been closed by a test that ran before
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(sessions_routes.delete_session(a.id, _="ok"))
    finally:
        loop.close()
    assert deleted.read_text(encoding="utf-8") == "a"
    assert memo_path(b.id).read_text(encoding="utf-8") == "b"


# --- What the tab's agent is told ---

def test_session_env_names_the_memo_of_that_tab(tabs):
    a, _ = tabs
    args = tmux_session_env_args(a.id, {"PWA_NOTE": "/spoof"})
    assert f"PWA_NOTE={memo_path(a.id)}" in args
    assert "PWA_NOTE=/spoof" not in args
