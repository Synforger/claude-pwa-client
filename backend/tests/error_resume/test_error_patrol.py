"""The error resume patrol types one message to carry on into a tab whose turn a passing API error ended, waits for it
to show, sends it once more when it does not, and gives up with one notice to the parent or the operator
(`error_resume/error_patrol.py`); the child watch keeps quiet about a child the error resume holds
(`child_watch/watch_sensors.py`). The record is a real file; sending, the push and the process table are replaced."""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

import backend.child_watch.watch_patrol as watch_patrol
import backend.child_watch.watch_sensors as watch_sensors
import backend.error_resume.error_patrol as patrol
import backend.error_resume.error_sensors as sensors
from backend._common import state as state_mod
from backend._common.state import ErrorResumeMark, SleepMark, register_session
from backend.account_fallback.fallback_sensors import TabBreak
from backend.accounts.tab_claim import claimed
from backend.error_resume.error_envelope import resume_envelope
from backend.error_resume.error_judgement import GIVE_UP, SEND, UNTAKEN_SEC
from backend.sleep.record_facts import ErrorStop
from backend.tests.async_run import run
from backend.tests.error_resume.samples import CUT_WORDS, error_row, prompt, resume_prompt


@pytest.fixture
def env(tmp_path, monkeypatch, isolated_state, agent_folder):
    """A tab whose conversation ends in a lost connection 2 minutes ago, its claude running and at a break."""
    tab = register_session("agent_a", title="Tab")
    now = time.time()
    record = tmp_path / "tab.jsonl"
    env = SimpleNamespace(tab=tab, record=record, now=now, sent=[], pushed=[], told=[], deliver=True, blocked_by=(),
                          may_run=True, tmp_path=tmp_path, agent_folder=agent_folder)
    _write(env, prompt("go", now - 300), error_row("e1", now - 120, api_error="connection_failed"))
    monkeypatch.setattr(sensors.jsonl_watcher, "get_jsonl_for", lambda _sid: record)
    monkeypatch.setattr(sensors, "claude_pid_in_pane", lambda _sid: 99)
    monkeypatch.setattr(sensors, "read_tab_break", lambda _sid: TabBreak(None, env.blocked_by))
    monkeypatch.setattr(sensors, "takes_asks", lambda _sid: False)
    monkeypatch.setattr(sensors, "_may_run", lambda _meta, _rows, _now: env.may_run)
    monkeypatch.setattr(sensors, "read_all_rate_limits_tail", lambda: [])
    monkeypatch.setattr(patrol, "read_all_rate_limits_tail", lambda: [])

    async def _send(session_id, text):
        env.sent.append((session_id, text))
        return env.deliver
    monkeypatch.setattr(patrol, "send_to_tab", _send)

    async def _told(session_id, text):
        env.told.append((session_id, text))
        return True
    monkeypatch.setattr(watch_patrol, "send_to_tab", _told)
    monkeypatch.setattr(watch_patrol, "_seen_at_break", {})

    async def _push(message, title=None, session_id=None, **_kw):
        env.pushed.append((session_id, message))
    monkeypatch.setattr(patrol, "broadcast_push", _push)
    return env


def _write(env, *rows: dict) -> None:
    env.record.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _append(env, *rows: dict) -> None:
    with env.record.open("a") as fh:
        fh.write("".join(json.dumps(row) + "\n" for row in rows))


def _stop(uuid: str = "e1") -> ErrorStop:
    return ErrorStop(uuid=uuid, at=0.0, error="server_error", cause="connection_failed", words=CUT_WORDS)


def _age_mark(env, seconds: float) -> None:
    mark = env.tab.error_resumed
    env.tab.error_resumed = ErrorResumeMark(stop=mark.stop, sent_at=mark.sent_at - seconds, sent_count=mark.sent_count)


def test_the_tab_is_sent_one_message_to_carry_on(env):
    assert run(patrol.tick()) == {env.tab.id: SEND}
    [(session_id, text)] = env.sent
    assert session_id == env.tab.id and text == resume_envelope(_stop(), 0)
    assert env.tab.error_resumed.stop == "e1" and env.tab.error_resumed.sent_count == 1
    assert run(patrol.tick()) == {} and len(env.sent) == 1              # waits for it to show in the record


def test_once_the_message_shows_the_stop_is_over(env):
    run(patrol.tick())
    _append(env, resume_prompt(env.now - 30), {"type": "assistant", "message": {"content": [{"type": "text",
                                                                                              "text": "on it"}]}})
    _age_mark(env, UNTAKEN_SEC + 1)
    assert run(patrol.tick()) == {} and len(env.sent) == 1


def test_a_message_that_does_not_show_is_sent_once_more_then_given_up_on(env):
    env.deliver = False
    assert run(patrol.tick()) == {env.tab.id: SEND}
    _age_mark(env, UNTAKEN_SEC + 1)
    assert run(patrol.tick()) == {env.tab.id: SEND} and env.tab.error_resumed.sent_count == 2
    _age_mark(env, UNTAKEN_SEC + 1)
    assert run(patrol.tick()) == {env.tab.id: GIVE_UP}
    assert env.tab.error_gave_up == "e1"
    [(session_id, words)] = env.pushed
    assert session_id == env.tab.id and CUT_WORDS in words
    assert run(patrol.tick()) == {} and len(env.sent) == 2 and len(env.pushed) == 1


def test_after_three_messages_that_met_the_error_again_the_operator_is_told_once(env):
    _write(env, prompt("go", env.now - 900), error_row("e0", env.now - 880),
           resume_prompt(env.now - 850), error_row("e1", env.now - 840),
           resume_prompt(env.now - 500), error_row("e2", env.now - 490),
           resume_prompt(env.now - 40), error_row("e3", env.now - 30))
    assert run(patrol.tick()) == {env.tab.id: GIVE_UP}
    assert env.sent == [] and env.tab.error_gave_up == "e3" and len(env.pushed) == 1


def test_a_tab_another_feature_works_on_is_left_alone(env):
    with claimed(env.tab.id):
        assert run(patrol.tick()) == {}
    env.tab.owes_carry_on = True
    assert run(patrol.tick()) == {}
    env.tab.owes_carry_on = False
    env.may_run = False
    assert run(patrol.tick()) == {} and env.sent == []


def test_a_sleeping_tab_is_sent_the_message_which_wakes_it(env, monkeypatch):
    monkeypatch.setattr(sensors.jsonl_watcher, "get_jsonl_for", lambda _sid: None)
    monkeypatch.setattr(sensors, "claude_pid_in_pane", lambda _sid: None)
    env.tab.sleep = SleepMark(claude_sid="c1", record=str(env.record), slept_at=int(env.now))
    assert run(patrol.tick()) == {env.tab.id: SEND}


def test_the_mark_survives_a_restart_of_the_backend(env):
    run(patrol.tick())
    state_mod.sessions_meta.clear()
    state_mod.sessions_meta.update(state_mod._load_sessions_meta())
    assert state_mod.sessions_meta[env.tab.id].error_resumed.stop == "e1"
    assert run(patrol.tick()) == {} and len(env.sent) == 1


def _child(env):
    child = register_session("agent_a", title="Child", child=True, parent_id=env.tab.id)
    memo = env.agent_folder / "pages" / child.id / "memo.md"
    memo.parent.mkdir(parents=True)
    memo.write_text(f"# {child.title}\n\n- 親のタブ: {env.tab.id}\n- 状態: 作業中\n", encoding="utf-8")
    return child


def test_the_watch_keeps_quiet_about_a_child_the_error_resume_carries_on(env, monkeypatch):
    child = _child(env)
    monkeypatch.setattr(watch_sensors.jsonl_watcher, "get_jsonl_for", lambda _sid: env.record)
    monkeypatch.setattr(watch_sensors, "read_tab_break", lambda _sid: TabBreak(None, ()))
    _write(env, prompt("go", env.now - 300), error_row("e1", env.now - 10))           # within the first wait
    assert run(watch_patrol.tick()) == [] and run(watch_patrol.tick()) == []
    assert env.told == [] and child.stop_told_at is None


def test_a_child_given_up_on_is_told_to_its_parent_once_with_its_reason(env, monkeypatch):
    child = _child(env)
    monkeypatch.setattr(watch_sensors.jsonl_watcher, "get_jsonl_for", lambda _sid: env.record)
    monkeypatch.setattr(watch_sensors, "read_tab_break", lambda _sid: TabBreak(None, ()))
    child.error_resumed = ErrorResumeMark(stop="e1", sent_at=env.now - UNTAKEN_SEC - 1, sent_count=2)
    env.tab.error_gave_up = "e1"                       # the parent tab's own copy of the stop is not this test's
    run(patrol.tick())
    assert child.error_gave_up == "e1" and env.pushed == []
    [(parent, text)] = env.told
    assert parent == env.tab.id and 'reason="api_error"' in text and child.id in text
    assert run(watch_patrol.tick()) == [] and run(watch_patrol.tick()) == [] and len(env.told) == 1


def test_a_child_the_error_resume_does_not_carry_on_is_told_by_the_watch_as_before(env, monkeypatch):
    child = _child(env)
    child.held_at = env.now - 60
    monkeypatch.setattr(watch_sensors.jsonl_watcher, "get_jsonl_for", lambda _sid: env.record)
    monkeypatch.setattr(watch_sensors, "read_tab_break", lambda _sid: TabBreak(None, ()))
    run(watch_patrol.tick())
    assert run(watch_patrol.tick()) == [child.id]
    assert 'reason="idle"' in env.told[0][1]
