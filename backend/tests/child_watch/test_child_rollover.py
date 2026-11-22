"""A child that reported (`完了` / `詰まり`) stays reported through an automatic rollover, and the child watch does not
tell its parent that it stopped. The whole rollover path is run for real (the ask to close, the restart of the tab, the
first message of the new conversation) with only the typing into the terminal and the restart of the tab's claude
replaced; the memo, the conversation record and the watch are real."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

import backend.child_watch.watch_patrol as patrol
import backend.rollover.rollover as watch
from backend.child_watch.child_memo import STUCK, WORKING, memo_state
from backend.child_watch.child_work import hand_work
from backend.child_watch.watch_sensors import is_watching
import backend.routes.sessions as sessions_routes
from backend.routes import rollover as ro
from backend.tests.async_run import run


@pytest.fixture
def rolling(env, monkeypatch):
    """The rollover of the child: what was typed into its terminal, in order, and the restarts of its claude."""
    typed: list[str] = []
    restarts: list[str] = []

    async def type_in(session_id, payload, idempotency_key=None, **_):
        assert session_id == env.child.id
        typed.append(payload["text"])
        return {"ok": True}

    async def restart(session_id, _caller):
        restarts.append(session_id)
        return {"ok": True}

    monkeypatch.setattr(watch, "pty_send", type_in)
    monkeypatch.setattr(ro, "pty_send", type_in)
    monkeypatch.setattr(sessions_routes, "restart_session", restart)
    monkeypatch.setattr(ro, "ROLL_DELAY_SEC", 0)
    return SimpleNamespace(typed=typed, restarts=restarts, roll=lambda: run(_roll_through(env.child.id)))


async def _roll_through(child_id: str) -> None:
    """The ask to close, then the restart and the first message of the next conversation."""
    await watch._ask(child_id, "record", "context", 70, 0, time.time(), again=False)
    await ro._roll(child_id, ro.start_envelope("tier=normal\nmode=continue"))


@pytest.mark.parametrize("reported", ["完了", STUCK])
def test_a_child_that_reported_is_still_reported_after_its_rollover(env, rolling, reported):
    env.memo.write_text(f"# T\n\n- 親のタブ: {env.parent.id}\n- 状態: {reported}\n\n## 引き継ぎ\n\nwait for the parent\n",
                        encoding="utf-8")
    before = env.memo.read_text(encoding="utf-8")
    rolling.roll()
    assert len(rolling.typed) == 2 and rolling.restarts == [env.child.id]        # the ask, then the first message
    assert memo_state(env.memo) == reported and env.memo.read_text(encoding="utf-8") == before


def test_the_parent_is_not_told_about_a_stuck_child_that_rolled_over(env, rolling):
    env.memo.write_text(f"# T\n\n- 状態: {STUCK}\n", encoding="utf-8")
    rolling.roll()
    assert not is_watching(env.child)
    assert [run(patrol.tick()) for _ in range(3)] == [[], [], []] and env.sent == []


def test_a_child_that_never_reported_is_still_told_about_after_its_rollover(env, rolling):
    """The other side of the same rule: the rollover changes nothing, so a child still working is watched as before."""
    rolling.roll()
    assert memo_state(env.memo) == WORKING and is_watching(env.child)
    run(patrol.tick())
    assert run(patrol.tick()) == [env.child.id]


def test_the_parent_s_message_after_the_rollover_still_sets_a_stuck_child_working(env, rolling):
    """What hands the child work again is the parent's message and nothing else."""
    env.memo.write_text(f"# T\n\n- 状態: {STUCK}\n", encoding="utf-8")
    rolling.roll()
    assert hand_work(env.parent.id, env.child.id) is True and memo_state(env.memo) == WORKING
