"""The limit resume patrol tells a tab that a usage limit stopped to carry on, once, when the limit is over
(`limit_resume/resume_patrol.py`). The usage log and the message sent are replaced; the record is a real file."""
from __future__ import annotations

import json
import logging
import time
from types import SimpleNamespace

import pytest

import backend.limit_resume.resume_patrol as patrol
from backend._common import state as state_mod
from backend._common.state import SleepMark, register_session
from backend.jsonl.jsonl_predicates import CLIENT_NOTICE_OPENING
from backend.limit_resume.resume_envelope import resume_envelope
from backend.tests.account_fallback.conftest import accounts_with_fallback, usage_row
from backend.tests.async_run import run
from backend.tests.limit_samples import iso, limit_stop_row, message_row, stopped_mid_turn, use_accounts


@pytest.fixture
def env(tmp_path, monkeypatch, isolated_state):
    """A tab on `personal` (no fallback) whose conversation ends in a limit stop 10 minutes ago."""
    use_accounts(monkeypatch, accounts_with_fallback())
    tab = register_session("agent_a", title="T", account_id="personal")
    now = time.time()
    record = tmp_path / "tab.jsonl"
    stop_at = now - 600
    record.write_text("\n".join(json.dumps(r) for r in stopped_mid_turn(iso(stop_at))) + "\n")
    env = SimpleNamespace(tab=tab, record=record, stop_at=stop_at, now=now, rows=[], sent=[], running=True,
                          deliver=True, tmp_path=tmp_path)
    monkeypatch.setattr(patrol.jsonl_watcher, "get_jsonl_for", lambda _sid: record)
    monkeypatch.setattr(patrol, "read_all_rate_limits_tail", lambda: env.rows)
    monkeypatch.setattr(patrol, "claude_pid_in_pane", lambda _sid: 99 if env.running else None)

    async def _send(session_id, text):
        env.sent.append((session_id, text))
        return env.deliver
    monkeypatch.setattr(patrol, "send_to_tab", _send)
    monkeypatch.setattr(patrol, "_seen_at_limit", {})
    return env


def _at_limit(env, account="personal", **fields):
    return usage_row(account, five=100, five_resets=env.now + 3600, ts=env.now - 60, **fields)


def _recovered(env, account="personal", pct=20):
    return usage_row(account, five=pct, ts=env.now - 5)


def test_a_stopped_tab_is_told_to_carry_on_when_the_usage_has_come_down_from_the_limit(env):
    env.rows = [_at_limit(env)]
    assert run(patrol.tick()) == [] and env.sent == []                  # the limit is still on
    env.rows = [_recovered(env)]
    assert run(patrol.tick()) == [env.tab.id]
    [(session_id, text)] = env.sent
    assert session_id == env.tab.id
    assert text == resume_envelope("personal")


def test_a_window_that_reset_after_the_stop_ends_it_even_when_the_stop_was_not_watched(env):
    env.rows = [usage_row("personal", five=100, five_resets=env.stop_at + 120, ts=env.stop_at - 30)]
    assert run(patrol.tick()) == [env.tab.id]


def test_the_message_has_the_envelope_of_the_clients_own_messages_and_names_the_account(env):
    text = resume_envelope("personal")
    assert text.splitlines()[0] == CLIENT_NOTICE_OPENING
    assert '<limit-resume account="personal">' in text and text.rstrip().endswith("</limit-resume>")
    assert "The usage limit has ended. Carry on with the work you were doing before it stopped." in text


def test_the_tab_of_an_account_with_a_fallback_is_the_resumes_once_the_account_is_back_under_its_line(env):
    env.tab.account_id = "work"
    env.rows = [usage_row("work", five=96, five_resets=env.now + 3600, ts=env.now - 60)]
    assert run(patrol.tick()) == [] and env.sent == []                  # at its line: the fallback's tab to move
    env.rows = [usage_row("work", five=94, ts=env.now - 5)]
    assert run(patrol.tick()) == [env.tab.id]
    assert env.sent[0][1] == resume_envelope("work")


def test_an_account_without_a_fallback_is_judged_against_100_percent(env):
    env.rows = [usage_row("personal", five=99, five_resets=env.now + 3600, ts=env.now - 60)]
    assert run(patrol.tick()) == []                                     # 99 is under the line: nothing explains the stop
    assert env.sent == []


def test_a_stop_the_usage_never_explained_is_not_answered(env):
    env.rows = [_recovered(env)]
    assert run(patrol.tick()) == [] and env.sent == []


def test_one_stop_is_answered_once_however_often_the_patrol_looks(env):
    env.rows = [_at_limit(env)]
    run(patrol.tick())
    env.rows = [_recovered(env)]
    assert run(patrol.tick()) == [env.tab.id]
    assert run(patrol.tick()) == [] and run(patrol.tick()) == []
    assert len(env.sent) == 1


def test_one_stop_is_answered_once_across_a_restart_of_the_backend(env, monkeypatch):
    env.rows = [_at_limit(env)]
    run(patrol.tick())
    env.rows = [_recovered(env)]
    run(patrol.tick())
    assert state_mod.SESSION_META_PATH.is_file()
    state_mod.sessions_meta.clear()
    state_mod.sessions_meta.update(state_mod._load_sessions_meta())          # what a restart reads back
    monkeypatch.setattr(patrol, "_seen_at_limit", {})
    assert state_mod.sessions_meta[env.tab.id].limit_resumed == "lim1"
    assert run(patrol.tick()) == [] and len(env.sent) == 1


def test_a_later_stop_is_answered_again(env):
    env.rows = [_at_limit(env)]
    run(patrol.tick())
    env.rows = [_recovered(env)]
    run(patrol.tick())
    with env.record.open("a") as fh:           # a record only grows: the tab was told, worked, and was stopped again
        for row in (message_row("u3", "lim1", "user", "go on"), limit_stop_row("lim2", "u3", iso(env.now - 60))):
            fh.write(json.dumps(row) + "\n")
    env.rows = [usage_row("personal", five=100, five_resets=env.now + 3600, ts=env.now - 30)]
    run(patrol.tick())
    env.rows = [usage_row("personal", five=10, ts=env.now)]
    assert run(patrol.tick()) == [env.tab.id] and len(env.sent) == 2


def test_a_message_that_did_not_arrive_is_tried_again_at_the_next_look(env):
    env.rows = [_at_limit(env)]
    run(patrol.tick())
    env.rows = [_recovered(env)]
    env.deliver = False
    assert run(patrol.tick()) == [] and env.tab.limit_resumed is None
    env.deliver = True
    assert run(patrol.tick()) == [env.tab.id] and env.tab.limit_resumed == "lim1"


def test_a_tab_asleep_is_given_the_message_that_wakes_it_in_the_same_conversation(env):
    env.tab.sleep = SleepMark(claude_sid="tab", record=str(env.record), slept_at=int(env.now - 300), account_id="personal")
    env.running = False                                                  # asleep: no claude runs
    env.rows = [_at_limit(env)]
    run(patrol.tick())
    env.rows = [_recovered(env)]
    assert run(patrol.tick()) == [env.tab.id]
    assert env.sent == [(env.tab.id, resume_envelope("personal"))]


def test_a_tab_that_is_awake_but_runs_nothing_is_not_started_for_this(env):
    env.running = False
    env.rows = [_at_limit(env)]
    run(patrol.tick())
    env.rows = [_recovered(env)]
    assert run(patrol.tick()) == [] and env.sent == []


def test_a_tab_the_other_feature_is_working_on_is_left_for_the_next_look(env):
    from backend.accounts.tab_claim import claimed  # noqa: PLC0415
    env.rows = [_at_limit(env)]
    run(patrol.tick())
    env.rows = [_recovered(env)]
    with claimed(env.tab.id):
        assert run(patrol.tick()) == [] and env.sent == [] and env.tab.limit_resumed is None
    assert run(patrol.tick()) == [env.tab.id]


def test_a_conversation_that_went_on_after_the_stop_is_not_a_stopped_tab(env):
    env.rows = [_at_limit(env)]
    run(patrol.tick())
    with env.record.open("a") as fh:
        fh.write(json.dumps({"type": "user", "uuid": "u9", "parentUuid": "lim1", "origin": {"kind": "human"},
                             "message": {"content": "hello"}}) + "\n")
    env.rows = [_recovered(env)]
    assert run(patrol.tick()) == [] and env.sent == []


def test_a_resume_is_logged(env, caplog):
    env.rows = [_at_limit(env)]
    run(patrol.tick())
    env.rows = [_recovered(env)]
    with caplog.at_level(logging.INFO):
        run(patrol.tick())
    assert any(r.getMessage().startswith(f"limit resume: session={env.tab.id} account=personal stop=lim1")
               for r in caplog.records)


def test_a_pinned_tab_is_told_to_carry_on_like_any_other(env):
    env.tab.account_pinned = True
    env.rows = [_at_limit(env)]
    run(patrol.tick())
    env.rows = [_recovered(env)]
    assert run(patrol.tick()) == [env.tab.id]
