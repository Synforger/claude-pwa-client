"""The child watch patrol tells a parent tab once when a child stopped without reporting (`child_watch/watch_patrol.py`).
The memo, the conversation record and the stop's samples are real files; what is read of the process table, and the
message sent, are replaced."""
from __future__ import annotations

import json
import logging
import time
from types import SimpleNamespace

import pytest

import backend.child_watch.watch_patrol as patrol
import backend.child_watch.watch_sensors as sensors
from backend._common import state as state_mod
from backend._common.state import SleepMark, register_session
from backend.account_fallback.fallback_sensors import TabBreak
from backend.child_watch.watch_envelope import child_stopped_envelope
from backend.child_watch.watch_judgement import IDLE, LIMIT
from backend.sleep.sleep_sensors import record_facts_of
from backend.tests.async_run import run
from backend.tests.limit_samples import iso, limit_notice_row, limit_reset_rows, message_row, stopped_mid_turn


def _answer(uuid: str, parent: str, at: float) -> dict:
    return message_row(uuid, parent, "assistant", [{"type": "text", "text": "done"}], iso(at))


@pytest.fixture
def env(tmp_path, monkeypatch, isolated_state, agent_folder):
    """A working child of a parent tab whose conversation ends in an answer 10 minutes ago, with its claude at a break."""
    parent = register_session("agent_a", title="Parent")
    child = register_session("agent_a", title="Build the parser", child=True, parent_id=parent.id)
    now = time.time()
    record = tmp_path / "child.jsonl"
    record.write_text(json.dumps(message_row("u1", None, "user", "go", iso(now - 700))) + "\n"
                      + json.dumps(_answer("a1", "u1", now - 600)) + "\n")
    memo = agent_folder / "pages" / child.id / "memo.md"
    memo.parent.mkdir(parents=True)
    memo.write_text(f"# {child.title}\n\n- 親のタブ: {parent.id}\n- 状態: 作業中\n", encoding="utf-8")
    env = SimpleNamespace(parent=parent, child=child, record=record, memo=memo, now=now, blocked_by=(), sent=[],
                          deliver=True)
    monkeypatch.setattr(sensors.jsonl_watcher, "get_jsonl_for", lambda _sid: record)

    def _break(_sid):
        facts = record_facts_of(record)
        return TabBreak(facts.limit_stop, env.blocked_by, owed=facts.continuation_owed)
    monkeypatch.setattr(sensors, "read_tab_break", _break)

    async def _send(session_id, text):
        env.sent.append((session_id, text))
        return env.deliver
    monkeypatch.setattr(patrol, "send_to_tab", _send)
    monkeypatch.setattr(patrol, "_seen_at_break", {})
    return env


def _last_row_time(env) -> float:
    return record_facts_of(env.record).last_row_at


def _append(env, *rows: dict) -> None:
    with env.record.open("a") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def test_a_child_at_a_break_is_not_told_about_on_the_first_look_but_on_the_second(env):
    assert run(patrol.tick()) == [] and env.sent == []
    assert run(patrol.tick()) == [env.child.id]
    assert env.sent == [(env.parent.id, child_stopped_envelope(env.child.id, "Build the parser", IDLE))]


def test_a_child_that_was_not_at_a_break_between_two_looks_starts_counting_again(env):
    run(patrol.tick())
    env.blocked_by = ("turn_open",)                                      # it is answering at the second look
    assert run(patrol.tick()) == []
    env.blocked_by = ()
    assert run(patrol.tick()) == [] and env.sent == []                   # first look of a new run
    assert run(patrol.tick()) == [env.child.id]


@pytest.mark.parametrize("reason", ["processes_running", "awaiting_tool_result", "wakeup_scheduled", "cron_scheduled",
                                    "turn_open", "voice_call", "rolling_over", "claude_not_running"])
def test_a_child_with_something_going_on_is_never_told_about(env, reason):
    env.blocked_by = (reason,)
    assert [run(patrol.tick()) for _ in range(3)] == [[], [], []] and env.sent == []


def test_a_stop_is_told_once_however_often_the_patrol_looks(env):
    for _ in range(5):
        run(patrol.tick())
    assert len(env.sent) == 1 and env.child.stop_told_at == _last_row_time(env)


def test_a_stop_is_told_once_across_a_restart_of_the_backend(env, monkeypatch):
    run(patrol.tick())
    run(patrol.tick())
    assert state_mod.SESSION_META_PATH.is_file()
    state_mod.sessions_meta.clear()
    state_mod.sessions_meta.update(state_mod._load_sessions_meta())           # what a restart reads back
    monkeypatch.setattr(patrol, "_seen_at_break", {})
    assert state_mod.sessions_meta[env.child.id].stop_told_at == _last_row_time(env)
    assert [run(patrol.tick()) for _ in range(3)] == [[], [], []] and len(env.sent) == 1


def test_a_child_that_works_on_and_stops_again_is_told_about_again(env):
    run(patrol.tick())
    run(patrol.tick())
    _append(env, message_row("u2", "a1", "user", "go on", iso(env.now - 300)), _answer("a2", "u2", env.now - 200))
    assert run(patrol.tick()) == [] and run(patrol.tick()) == [env.child.id]
    assert len(env.sent) == 2 and env.child.stop_told_at == _last_row_time(env)


def test_a_usage_limit_stop_is_told_with_the_reason_limit(env):
    _append(env, *stopped_mid_turn(iso(env.now - 300))[1:])
    run(patrol.tick())
    assert run(patrol.tick()) == [env.child.id]
    assert env.sent == [(env.parent.id, child_stopped_envelope(env.child.id, "Build the parser", LIMIT))]


def test_a_limit_notice_alone_is_told_with_the_reason_limit(env):
    _append(env, limit_notice_row("n1", "a1", iso(env.now - 300)))
    run(patrol.tick())
    assert run(patrol.tick()) == [env.child.id]
    assert env.sent[0][1] == child_stopped_envelope(env.child.id, "Build the parser", LIMIT)


def test_a_continuation_still_owed_after_the_stop_was_answered_is_told_with_the_reason_limit(env):
    """An answer to a background notification ends the stop, but the continuation Claude Code booked stays owed."""
    notification = {"type": "user", "uuid": "t1", "parentUuid": "n1", "timestamp": iso(env.now - 200),
                    "origin": {"kind": "task-notification"}, "message": {"content": "<task-notification>x</task-notification>"}}
    _append(env, limit_notice_row("n1", "a1", iso(env.now - 300)), notification, _answer("a2", "t1", env.now - 100))
    assert record_facts_of(env.record).limit_stop is None
    run(patrol.tick())
    assert run(patrol.tick()) == [env.child.id]
    assert env.sent[0][1] == child_stopped_envelope(env.child.id, "Build the parser", LIMIT)


def test_a_continuation_settled_by_the_reset_leaves_a_plain_idle_stop(env):
    _append(env, limit_notice_row("n1", "a1", iso(env.now - 300)), *limit_reset_rows("n1", iso(env.now - 200)),
            _answer("a2", "reset-prompt", env.now - 100))
    run(patrol.tick())
    assert run(patrol.tick()) == [env.child.id]
    assert env.sent[0][1] == child_stopped_envelope(env.child.id, "Build the parser", IDLE)


@pytest.mark.parametrize("memo_state", ["完了", "詰まり"])
def test_a_child_that_reported_is_not_told_about(env, memo_state):
    env.memo.write_text(f"# T\n\n- 状態: {memo_state}\n", encoding="utf-8")
    assert [run(patrol.tick()) for _ in range(3)] == [[], [], []] and env.sent == []


def test_a_child_without_a_memo_is_not_told_about(env):
    env.memo.unlink()
    assert [run(patrol.tick()) for _ in range(3)] == [[], [], []] and env.sent == []


def test_a_memo_in_the_parents_tier_folder_counts_like_one_in_the_childs(env, monkeypatch):
    """`tabs new` writes the memo where the parent's tier is, and the child may have started in another."""
    seen = []

    def _tier_folder(tab_id):
        seen.append(tab_id)
        return env.memo.parents[2] if tab_id == env.parent.id else env.memo.parents[2] / "elsewhere"
    monkeypatch.setattr(sensors, "tier_folder", _tier_folder)
    run(patrol.tick())
    assert run(patrol.tick()) == [env.child.id] and seen[:2] == [env.child.id, env.parent.id]


def test_a_sleeping_child_is_not_told_about(env):
    env.child.sleep = SleepMark(claude_sid="child", record=str(env.record), slept_at=int(env.now - 300))
    assert [run(patrol.tick()) for _ in range(3)] == [[], [], []] and env.sent == []


def test_a_tab_that_is_not_a_child_is_not_told_about(env):
    env.child.child = False
    assert [run(patrol.tick()) for _ in range(3)] == [[], [], []] and env.sent == []


def test_a_child_whose_parent_is_gone_is_not_told_about(env):
    state_mod.sessions_meta.pop(env.parent.id)
    assert [run(patrol.tick()) for _ in range(3)] == [[], [], []] and env.sent == []


def test_a_child_without_a_row_time_is_not_told_about(env):
    env.record.write_text(json.dumps({"type": "user", "uuid": "u1", "message": {"content": "go"}}) + "\n")
    assert [run(patrol.tick()) for _ in range(3)] == [[], [], []] and env.sent == []


def test_a_message_that_did_not_arrive_is_tried_again_at_the_next_look(env):
    env.deliver = False
    run(patrol.tick())
    assert run(patrol.tick()) == [] and env.child.stop_told_at is None
    env.deliver = True
    assert run(patrol.tick()) == [env.child.id] and env.child.stop_told_at == _last_row_time(env)


def test_a_parent_the_other_features_are_working_on_is_left_for_the_next_look(env):
    from backend.accounts.tab_claim import claimed  # noqa: PLC0415
    run(patrol.tick())
    with claimed(env.parent.id):
        assert run(patrol.tick()) == [] and env.sent == [] and env.child.stop_told_at is None
    assert run(patrol.tick()) == [env.child.id]


def test_a_message_is_logged_with_the_child_the_parent_and_the_reason(env, caplog):
    run(patrol.tick())
    with caplog.at_level(logging.INFO):
        run(patrol.tick())
    assert any(r.getMessage() == f"child watch: session={env.child.id} parent={env.parent.id} reason=idle sent=True"
               for r in caplog.records)


def test_a_child_that_left_the_list_is_forgotten(env):
    run(patrol.tick())
    assert env.child.id in patrol._seen_at_break
    state_mod.sessions_meta.pop(env.child.id)
    run(patrol.tick())
    assert patrol._seen_at_break == {}


def test_a_failing_look_does_not_stop_the_loop_after_it(env, monkeypatch, caplog):
    import asyncio  # noqa: PLC0415

    def _boom(_sid):
        raise RuntimeError("boom")
    monkeypatch.setattr(sensors, "read_tab_break", _boom)

    async def _loop():
        task = asyncio.create_task(patrol.watch_loop(0.01))
        await asyncio.sleep(0.1)
        alive = not task.done()
        task.cancel()
        return alive
    with caplog.at_level(logging.ERROR):
        assert run(_loop()) is True
    assert any("watch_loop iteration failed" in r.getMessage() for r in caplog.records)
