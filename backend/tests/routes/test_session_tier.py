"""The tier each tab was started in: listed on the tab rows and the overview, and recorded when the tab's
claude is found."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.routes.overview as overview
from backend.terminal import pty_discover, tab_tier


@pytest.fixture
def tabs(isolated_state, monkeypatch):
    monkeypatch.setattr(isolated_state, "save_sessions_meta", lambda: None)
    return isolated_state.register_session("agent_a", title="A"), isolated_state.register_session("agent_a", title="B")


@pytest.fixture
def client(tabs):
    # The tab routes hold the config as it is when they are loaded: load them after the test's config is in place.
    import backend.routes.sessions as sessions  # noqa: PLC0415
    app = FastAPI()
    app.include_router(sessions.router)
    return TestClient(app)


def test_every_row_has_a_tier_and_it_is_null_when_not_known(client, tabs):
    a, b = tabs
    a.tier = "projects/alpha"
    rows = {row["id"]: row for row in client.get("/sessions").json()}
    assert rows[a.id]["tier"] == "projects/alpha"
    assert "tier" in rows[b.id] and rows[b.id]["tier"] is None


def test_the_title_stays_what_the_user_set(client, tabs):
    a, _ = tabs
    a.tier = "projects/alpha"
    renamed = client.patch(f"/sessions/{a.id}", json={"title": "my own name"}).json()
    assert renamed["title"] == "my own name" and renamed["tier"] == "projects/alpha"
    assert {row["id"]: row["title"] for row in client.get("/sessions").json()}[a.id] == "my own name"


def test_the_tier_is_stored_with_the_tab_and_comes_back_when_the_backend_loads_it(tabs, isolated_state, tmp_path, monkeypatch):
    a, _ = tabs
    a.tier = "projects/alpha"
    path = tmp_path / "stored_meta.json"
    path.write_text(json.dumps([a.to_dict()]))
    monkeypatch.setattr(isolated_state, "SESSION_META_PATH", path)
    loaded = isolated_state._load_sessions_meta()
    assert loaded[a.id].tier == "projects/alpha"


def test_the_overview_carries_the_tier_of_each_tab(tabs):
    a, b = tabs
    a.tier = "normal"
    payload = overview._build_sessions_overview()
    assert payload[a.id]["tier"] == "normal"
    assert payload[b.id]["tier"] is None


def test_finding_the_claude_of_a_tab_records_its_tier_and_wakes_the_overview(tabs, monkeypatch):
    a, _ = tabs
    woken = []
    claude = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                              env={"PATH": os.environ["PATH"], "AGENT_TIER": "projects/alpha"})
    try:
        monkeypatch.setattr(pty_discover, "tmux_pane_pids", lambda sid: [111])
        monkeypatch.setattr(pty_discover, "_find_claude_descendant_info", lambda pid: (claude.pid, 1.0, "/work"))
        monkeypatch.setattr(pty_discover.sessions_overview, "notify", lambda: woken.append(True))
        import backend.jsonl.jsonl_watcher as jsonl_watcher  # noqa: PLC0415
        monkeypatch.setattr(jsonl_watcher, "register_pending", lambda *args: None)

        asyncio.run(pty_discover.register_claude_when_ready(a.id, max_wait=2.0, interval=0.01))
    finally:
        claude.kill()
        claude.wait()
    assert tab_tier.tab_tier(a.id) == "projects/alpha"
    assert woken == [True]
