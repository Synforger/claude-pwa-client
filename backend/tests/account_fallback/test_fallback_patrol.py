"""The account fallback patrol moves the tabs of an account at its line and brings them back (`fallback_patrol.py`).
The move is the real one; the usage log, what is read about the tab and the message sent are the fixture's."""
from __future__ import annotations

import json
import logging
import sys
import time

import pytest

import backend._common.config as config
import backend.account_fallback.fallback_patrol as patrol
import backend.push.push as push
import backend.terminal.session_resolver as session_resolver
from backend._common.state import SleepMark, register_session, sessions_meta
from backend.account_fallback.fallback_sensors import TabBreak
from backend.routes.agent_messages import allowed_for_peer
from backend.tests.account_fallback.conftest import usage_row
from backend.tests.async_run import run
from backend.tests.limit_samples import use_accounts


def _copy_of(env):
    return env.src.parent / f"{env.tab.resume_session_id}.jsonl"


def _uuids(path) -> list[str]:
    return [json.loads(line)["uuid"] for line in path.read_text().splitlines() if line.strip()]


def test_a_tab_on_the_account_at_its_line_moves_to_the_fallback_account_at_a_break(env):
    env.rows = [usage_row(five=96)]
    assert run(patrol.tick()) == [env.tab.id]
    assert (env.tab.account_id, env.tab.fallback_from) == ("personal", "work")
    assert env.events == [f"kill {env.tab.id}", f"spawn {env.tab.id}"]
    assert env.tab.fallback_copy == str(_copy_of(env)) and _copy_of(env).is_file()


def test_a_tab_that_was_not_stopped_is_moved_without_a_word_to_it(env):
    env.rows = [usage_row(five=96)]
    run(patrol.tick())
    assert env.sent == []


def test_a_tab_the_limit_stopped_is_moved_with_its_tool_results_and_told_to_carry_on(env):
    env.rows = [usage_row(five=100)]
    env.stopped()
    run(patrol.tick())
    assert _uuids(_copy_of(env)) == ["u1", "a1", "u2"]                  # the limit's own row is left out
    [(session_id, text)] = env.sent
    assert session_id == env.tab.id
    assert text.splitlines()[0].startswith("Automatic session rollover, sent by the client")
    assert '<account-move from="work" to="personal" reason="limit">' in text
    assert "Carry on with the work you were doing before it stopped." in text


@pytest.mark.parametrize("seven_only", [False, True])
def test_the_five_hour_and_the_seven_day_usage_both_count(env, seven_only):
    env.rows = [usage_row(five=10, seven=97) if seven_only else usage_row(five=97, seven=10)]
    assert run(patrol.tick()) == [env.tab.id]


def test_a_tab_stays_while_the_usage_is_under_the_line(env):
    env.rows = [usage_row(five=94, seven=94)]
    assert run(patrol.tick()) == [] and env.tab.account_id == "work" and env.events == []


def test_a_tab_that_is_not_at_a_break_stays_and_the_reasons_are_logged_once(env, caplog):
    env.rows = [usage_row(five=100)]
    env.blocked_by = ("turn_open", "processes_running")
    with caplog.at_level(logging.INFO):
        run(patrol.tick())
        run(patrol.tick())
    assert env.tab.account_id == "work" and env.events == []
    waits = [r.getMessage() for r in caplog.records if "account fallback: waits" in r.getMessage()]
    assert len(waits) == 1 and "reasons=turn_open,processes_running" in waits[0]


def test_without_a_fallback_in_the_configuration_nothing_moves(env, monkeypatch):
    use_accounts(monkeypatch, {"personal": {"env": {}}, "work": {"env": {"CLAUDE_CONFIG_DIR": "/nonexistent-work"}}})
    env.rows = [usage_row(five=100)]
    assert run(patrol.tick()) == [] and env.tab.account_id == "work" and env.events == []


def test_a_tab_of_the_account_that_has_no_fallback_is_not_moved_even_at_its_limit(env):
    personal_tab = register_session(env.tab.agent_id, title="P", account_id="personal")
    env.rows = [usage_row("personal", five=100, seven=100)]
    assert run(patrol.tick()) == [] and personal_tab.account_id == "personal" and env.events == []


def test_the_usage_of_the_account_it_moves_to_does_not_hold_the_tab(env):
    env.rows = [usage_row("personal", five=100, seven=100), usage_row(five=99)]
    assert run(patrol.tick()) == [env.tab.id] and env.tab.account_id == "personal"


def test_a_child_tab_moves_like_any_tab_and_keeps_its_id_and_parent(env):
    env.tab.child, env.tab.parent_id = True, "ses_parent000000"
    tab_id = env.tab.id
    env.rows = [usage_row(five=100)]
    assert run(patrol.tick()) == [tab_id]
    assert (sessions_meta[tab_id].child, sessions_meta[tab_id].parent_id) == (True, "ses_parent000000")
    assert sessions_meta[tab_id].account_id == "personal"


def _moved(env):
    env.rows = [usage_row(five=100)]
    run(patrol.tick())
    assert env.tab.fallback_from == "work"
    env.events.clear()


def test_a_moved_tab_comes_back_when_the_usage_is_under_the_line_and_the_record_the_client_wrote_goes(env, caplog):
    _moved(env)
    copy = _copy_of(env)
    env.rows = [usage_row(five=100), usage_row(five=40)]
    with caplog.at_level(logging.INFO):
        assert run(patrol.tick()) == [env.tab.id]
    assert (env.tab.account_id, env.tab.fallback_from, env.tab.fallback_copy) == ("work", None, None)
    assert not copy.exists()
    messages = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("account fallback: returned") for m in messages)
    assert any(m.startswith("account move: deleted the record the client wrote") for m in messages)


def test_a_moved_tab_comes_back_when_the_window_that_stopped_it_has_reset(env):
    _moved(env)
    env.rows = [usage_row(five=100, five_resets=time.time() - 60)]
    assert run(patrol.tick()) == [env.tab.id] and env.tab.account_id == "work"


def test_a_moved_tab_stays_while_the_account_is_still_at_its_line_or_the_tab_is_not_at_a_break(env):
    _moved(env)
    assert run(patrol.tick()) == [] and env.tab.account_id == "personal"
    env.rows = [usage_row(five=10)]
    env.blocked_by = ("awaiting_tool_result",)
    assert run(patrol.tick()) == [] and env.tab.account_id == "personal"


def test_a_move_is_logged(env, caplog):
    env.rows = [usage_row(five=100)]
    with caplog.at_level(logging.INFO):
        run(patrol.tick())
    assert any(r.getMessage() == f"account fallback: moved session={env.tab.id} from=work to=personal "
                                 f"stopped_by_limit=False" for r in caplog.records)


def test_no_push_notification_is_sent(env, monkeypatch):
    async def _no(*_a, **_k):
        raise AssertionError("a push notification was sent")
    monkeypatch.setattr(push, "broadcast_push", _no)
    env.rows = [usage_row(five=100)]
    run(patrol.tick())
    env.rows = [usage_row(five=0)]
    run(patrol.tick())


def test_a_move_that_fails_leaves_the_tab_where_it_is_and_the_next_look_tries_again(env, monkeypatch):
    failing = [sys.executable, "-c", "import sys; sys.exit(1)"]
    monkeypatch.setattr(config, "LINEAGE_HOOK", failing, raising=False)
    env.rows = [usage_row(five=100)]
    assert run(patrol.tick()) == [] and env.tab.account_id == "work" and env.events == []
    assert list(env.src.parent.glob("*.jsonl")) == [env.src]            # no record of the failed attempt stays
    monkeypatch.setattr(config, "LINEAGE_HOOK", [], raising=False)
    assert run(patrol.tick()) == [env.tab.id] and env.tab.account_id == "personal"


# --- a tab asleep ---

def _asleep(env):
    env.tab.sleep = SleepMark(claude_sid="OLD", record=str(env.src), slept_at=int(time.time()), account_id="work")


def test_the_patrol_does_not_move_a_tab_that_is_asleep(env):
    _asleep(env)
    env.rows = [usage_row(five=100)]
    assert run(patrol.tick()) == [] and env.tab.account_id == "work" and env.events == []


def test_a_tab_asleep_is_moved_when_it_is_woken_while_its_account_is_at_the_line(env):
    _asleep(env)
    env.rows = [usage_row(five=100)]
    run(patrol.move_before_wake(env.tab.id))
    assert (env.tab.account_id, env.tab.fallback_from) == ("personal", "work")
    assert env.events == [f"kill {env.tab.id}", f"spawn {env.tab.id}"]
    assert env.sent == []                                               # the message that woke it is what it reads


def test_a_tab_asleep_wakes_where_it_slept_when_its_account_is_not_at_the_line(env):
    _asleep(env)
    env.rows = [usage_row(five=50)]
    run(patrol.move_before_wake(env.tab.id))
    assert env.tab.account_id == "work" and env.events == []


def test_reopening_a_sleeping_tab_asks_the_wake_hook_first_and_a_failing_hook_does_not_stop_the_reopening(
        env, monkeypatch):
    import asyncio  # noqa: PLC0415
    asked: list[str] = []

    async def _hook(session_id):
        asked.append(session_id)
        raise RuntimeError("the hook broke")
    monkeypatch.setattr(session_resolver, "_wake_hook", _hook)
    session_resolver.pty_sessions[env.tab.id] = type("Running", (), {"exit_event": asyncio.Event()})()
    try:
        run(session_resolver.ensure_pty_session_for(env.tab.id))               # awake: the hook is not asked
        assert asked == []
        _asleep(env)
        run(session_resolver.ensure_pty_session_for(env.tab.id))
        assert asked == [env.tab.id]
    finally:
        session_resolver.pty_sessions.pop(env.tab.id, None)


# --- another machine ---

def test_a_moved_tab_is_judged_for_other_machines_by_the_account_it_belongs_to(env):
    peer = {"accounts": ["work"]}
    env.tab.account_id, env.tab.fallback_from = "personal", "work"
    assert allowed_for_peer(peer, env.tab.id) is True
    env.tab.fallback_from = None
    assert allowed_for_peer(peer, env.tab.id) is False


def test_a_tab_blocks_nothing_it_was_not_asked_about(env):
    assert TabBreak(None, ()).at_break and not TabBreak(None, ("turn_open",)).at_break
