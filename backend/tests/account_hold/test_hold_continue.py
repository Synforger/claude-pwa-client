"""The operator continues the tabs the account hold stopped (`hold_continue.py`, `POST /accounts/{account}/continue`)."""
from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from backend._common.state import SleepMark, register_session
from backend.account_hold import hold_continue
from backend.account_hold.hold_continue import StillAtLine, continue_account
from backend.account_hold.hold_envelope import CONTINUE
from backend.jsonl.jsonl_predicates import CLIENT_NOTICE_OPENING
from backend.routes import account_hold as account_hold_routes
from backend.tests.account_hold.conftest import usage_row
from backend.tests.async_run import run


def _held(tab, at=100.0):
    tab.held_at = at
    tab.sleep = SleepMark(claude_sid="c1", record="/r.jsonl", slept_at=1)


def test_the_tabs_of_the_account_that_were_stopped_are_sent_the_message_and_lose_their_mark(env, caplog):
    _held(env.tab)
    free = register_session("agent_a", "not stopped", account_id="personal")
    env.rows = [usage_row(seven=10)]
    caplog.set_level(logging.INFO, logger=hold_continue.logger.name)
    result = run(continue_account("personal"))
    assert (result.continued, result.failed) == ((env.tab.id,), ())
    [(session_id, text)] = env.sent
    assert session_id == env.tab.id and text.splitlines()[0] == CLIENT_NOTICE_OPENING
    assert f'<account-hold phase="{CONTINUE}" account="personal">' in text
    assert env.tab.held_at is None and free.held_at is None
    assert f"account hold: continued session={env.tab.id} account=personal" in caplog.text


def test_it_is_refused_while_the_usage_is_still_at_the_line_and_nothing_changes(env):
    _held(env.tab)
    env.rows = [usage_row(seven=70)]
    with pytest.raises(StillAtLine) as refused:
        run(continue_account("personal"))
    assert refused.value.line_pct == 70
    assert env.sent == [] and env.tab.held_at == 100.0


def test_the_tabs_of_another_account_are_not_continued(env):
    _held(env.other)
    env.rows = [usage_row(seven=10)]
    assert run(continue_account("personal")).continued == () and env.other.held_at == 100.0 and env.sent == []


def test_a_tab_that_did_not_take_the_message_keeps_its_mark(env):
    _held(env.tab)
    env.rows = [usage_row(seven=10)]
    env.deliver = False
    result = run(continue_account("personal"))
    assert (result.continued, result.failed) == ((), (env.tab.id,)) and env.tab.held_at == 100.0


def test_an_account_without_a_hold_is_continued_without_a_line_to_check(env, monkeypatch):
    from backend.tests.limit_samples import use_accounts
    use_accounts(monkeypatch, {"personal": {"env": {}}})
    _held(env.tab)
    env.rows = [usage_row(seven=100)]
    assert run(continue_account("personal")).continued == (env.tab.id,)


def test_a_log_that_says_nothing_does_not_hold_the_tabs_back(env):
    _held(env.tab)
    env.rows = []
    assert run(continue_account("personal")).continued == (env.tab.id,)


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(account_hold_routes.router)
    return TestClient(app)


def test_the_route_continues_the_tabs_and_names_them(env, client):
    _held(env.tab)
    env.rows = [usage_row(seven=10)]
    answer = client.post("/accounts/personal/continue")
    assert answer.status_code == 200 and answer.json() == {"continued": [env.tab.id], "failed": []}


def test_the_route_answers_409_while_the_usage_is_at_the_line(env, client):
    _held(env.tab)
    env.rows = [usage_row(seven=95)]
    answer = client.post("/accounts/personal/continue")
    assert answer.status_code == 409
    assert answer.json()["detail"]["code"] == "still_at_line" and answer.json()["detail"]["params"] == {"line_pct": 70}
    assert env.tab.held_at == 100.0


def test_the_route_answers_404_for_an_account_that_is_not_configured(env, client):
    assert client.post("/accounts/nobody/continue").status_code == 404
