"""The account a sleeping tab runs on once it is woken, on the rows of `GET /sessions` and in the overview, so that the
screen and `tabs list` show it beside the account the tab last ran on."""
from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.routes.overview as overview
import backend.usage.usage as usage_log
from backend.tests.account_fallback.conftest import accounts_with_fallback, usage_row
from backend.tests.limit_samples import use_accounts


@pytest.fixture
def tabs(isolated_state, monkeypatch):
    """A tab on `work` (whose fallback is `personal`) that sleeps, and one that is awake. `usage` is the usage log."""
    monkeypatch.setattr(isolated_state, "save_sessions_meta", lambda: None)
    use_accounts(monkeypatch, accounts_with_fallback())
    usage: list[dict] = []
    monkeypatch.setattr(usage_log, "read_all_rate_limits_tail", lambda: usage)
    monkeypatch.setattr(overview, "_read_rate_limits_tail_cached", lambda: usage)
    asleep = isolated_state.register_session("agent_a", title="asleep", account_id="work")
    awake = isolated_state.register_session("agent_a", title="awake", account_id="work")
    asleep.sleep = isolated_state.SleepMark(claude_sid="OLD", record="/tmp/old.jsonl", slept_at=int(time.time()),
                                            account_id="work")
    return asleep, awake, usage


@pytest.fixture
def client(tabs):
    import backend.routes.sessions as sessions  # noqa: PLC0415 (= loaded after the test's configuration is in place)
    app = FastAPI()
    app.include_router(sessions.router)
    return TestClient(app)


def test_a_sleeping_tab_row_carries_the_account_it_wakes_on_and_an_awake_tab_row_carries_none(client, tabs):
    asleep, awake, usage = tabs
    usage.append(usage_row(five=100))
    rows = {row["id"]: row for row in client.get("/sessions").json()}
    assert rows[asleep.id]["account_on_wake"] == "personal" and rows[asleep.id]["account_id"] == "work"
    assert rows[awake.id]["account_on_wake"] is None


def test_the_overview_carries_it_too(tabs):
    asleep, awake, usage = tabs
    usage.append(usage_row(five=50))
    body = overview._build_sessions_overview()
    assert body[asleep.id]["account_on_wake"] == "work"
    assert body[awake.id]["account_on_wake"] is None
