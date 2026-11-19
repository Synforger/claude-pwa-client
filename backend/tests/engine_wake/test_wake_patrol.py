"""The patrol wakes an engine a voice uses and puts to rest one no voice has used for its idle time, and a speech
wakes the engine it needs (`backend/engine_wake/wake_patrol.py`). launchd and the engine are made up: `start` makes
the engine take connections after a moment, `stop` makes it refuse them."""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

import backend.engine_wake.wake_patrol as patrol
from backend.tests.async_run import run

URL = "http://127.0.0.1:10101"
LABEL = "x.voice"


@pytest.fixture
def engine(monkeypatch):
    """One engine named by agent `agent_v`, down; what launchd was asked; the tab `ses_v` of that agent."""
    fake = SimpleNamespace(up=False, calls=[], start_failure="", wakes_after=0.05, warmed=[], down_after=0.0)

    def answers(url: str) -> bool:
        return fake.up

    def start(label: str) -> str:
        fake.calls.append(("start", label))
        if not fake.start_failure:
            asyncio.run_coroutine_threadsafe(_come_up(), loop_of[0])
        return fake.start_failure

    async def _come_up():
        await asyncio.sleep(fake.wakes_after)
        fake.up = True

    def stop(label: str) -> str:
        fake.calls.append(("stop", label))
        fake.up = False
        return ""

    def warm(url: str, speaker) -> bool:
        fake.warmed.append(speaker)
        return True

    loop_of = [None]
    agents = {"agent_v": {"voice": {"engine": URL, "speaker": 7, "engine_service": {"label": LABEL, "idle_minutes": 10}}}}
    monkeypatch.setattr(patrol.config, "AGENTS", agents)
    monkeypatch.setattr(patrol, "resolve_agent_cfg", lambda sid: agents["agent_v"] if sid == "ses_v" else None)
    monkeypatch.setattr(patrol.engine_service, "answers", answers)
    monkeypatch.setattr(patrol.engine_service, "start", start)
    monkeypatch.setattr(patrol.engine_service, "stop", stop)
    monkeypatch.setattr(patrol.engine_service, "warm", warm)
    monkeypatch.setattr(patrol, "POLL_SEC", 0.01)
    monkeypatch.setattr(patrol, "_engines", {})
    monkeypatch.setattr(patrol, "_tasks", set())
    monkeypatch.setattr(patrol, "_started_at", time.time())
    monkeypatch.setattr(patrol, "voices_by_conn", {})
    monkeypatch.setattr(patrol, "calls_by_conn", {})
    fake.loop_of = loop_of
    return fake


async def _settled(engine) -> None:
    """Run the look's spawned wake or rest to its end."""
    engine.loop_of[0] = asyncio.get_running_loop()
    await patrol.look()
    while patrol._tasks:
        await asyncio.gather(*list(patrol._tasks))


def _look(engine) -> None:
    run(_settled(engine))


def test_a_voice_that_opens_wakes_its_engine_and_warms_its_voice(engine):
    patrol.voices_by_conn["conn"] = {"ses_v"}
    _look(engine)
    assert engine.calls == [("start", LABEL)] and engine.up and engine.warmed == [7]


def test_a_call_wakes_its_engine_too(engine):
    patrol.calls_by_conn["pc"] = "ses_v"
    _look(engine)
    assert engine.calls == [("start", LABEL)]


def test_an_engine_no_voice_used_for_its_idle_time_is_put_to_rest(engine, monkeypatch):
    engine.up = True
    _look(engine)
    assert engine.calls == []                                            # just started: not at once
    monkeypatch.setattr(patrol, "_started_at", time.time() - 11 * 60)
    patrol._engines.clear()
    _look(engine)
    assert engine.calls == [("stop", LABEL)] and not engine.up


def test_an_engine_that_is_down_is_not_put_to_rest(engine, monkeypatch):
    monkeypatch.setattr(patrol, "_started_at", time.time() - 60 * 60)
    _look(engine)
    assert engine.calls == []


def test_an_engine_woken_while_its_voice_closed_rests_ten_minutes_after_waking(engine, monkeypatch):
    monkeypatch.setattr(patrol, "_started_at", time.time() - 60 * 60)   # long after the backend's start
    patrol.voices_by_conn["conn"] = {"ses_v"}
    _look(engine)
    patrol.voices_by_conn.clear()
    _look(engine)
    assert engine.calls == [("start", LABEL)]                            # woken just now: kept
    patrol._engines[URL].last_used -= 10 * 60
    _look(engine)
    assert engine.calls[-1] == ("stop", LABEL)


def test_a_wake_that_fails_is_not_tried_again_for_a_while(engine):
    engine.start_failure = "Could not find service"
    patrol.voices_by_conn["conn"] = {"ses_v"}
    _look(engine)
    _look(engine)
    assert engine.calls == [("start", LABEL)]
    patrol._engines[URL].failed_at -= patrol.RETRY_SEC
    _look(engine)
    assert engine.calls == [("start", LABEL), ("start", LABEL)]


def test_a_speech_wakes_the_engine_it_needs_and_two_at_once_start_it_once(engine):
    async def two():
        engine.loop_of[0] = asyncio.get_running_loop()
        await asyncio.gather(patrol.ensure_awake(URL), patrol.ensure_awake(URL + "/"))
    run(two())
    assert engine.calls == [("start", LABEL)] and engine.up and engine.warmed == []


def test_a_speech_to_an_engine_that_does_not_wake_in_time_goes_on_and_fails_as_before(engine, monkeypatch):
    monkeypatch.setattr(patrol, "WAKE_TIMEOUT_SEC", 0.05)
    engine.wakes_after = 5.0

    async def one():
        engine.loop_of[0] = asyncio.get_running_loop()
        await patrol.ensure_awake(URL)
    run(one())
    assert engine.calls == [("start", LABEL)] and not engine.up


def test_a_speech_during_a_rest_waits_for_it_and_then_wakes_the_engine(engine):
    engine.up = True

    async def rest_then_speak():
        engine.loop_of[0] = asyncio.get_running_loop()
        service = patrol._services()[URL]
        state = patrol._engine_of(URL)
        resting = asyncio.create_task(patrol._stop(service, state))
        await asyncio.sleep(0)
        await patrol.ensure_awake(URL)
        await resting
    run(rest_then_speak())
    assert engine.calls == [("stop", LABEL), ("start", LABEL)] and engine.up


def test_an_engine_no_agent_names_is_left_alone(engine):
    run(patrol.ensure_awake("http://127.0.0.1:9999"))
    assert engine.calls == []


def test_the_end_to_end_backend_runs_no_patrol(monkeypatch):
    monkeypatch.setenv("CPC_E2E", "1")
    run(asyncio.wait_for(patrol.wake_loop(interval_sec=0.01), timeout=1))


def test_an_engine_its_service_keeps_alive_is_rested_once_and_then_left(engine, monkeypatch):
    monkeypatch.setattr(patrol, "_started_at", time.time() - 60 * 60)
    engine.up = True
    _look(engine)
    assert engine.calls == [("stop", LABEL)]
    engine.up = True                                                     # launchd started it again by itself
    _look(engine)
    _look(engine)
    assert engine.calls == [("stop", LABEL)] and patrol._engines[URL].kept_alive


def test_an_engine_the_patrol_woke_after_a_rest_is_not_taken_as_kept_alive(engine, monkeypatch):
    monkeypatch.setattr(patrol, "_started_at", time.time() - 60 * 60)
    engine.up = True
    _look(engine)                                                        # rested
    patrol.voices_by_conn["conn"] = {"ses_v"}
    _look(engine)                                                        # woken by the patrol
    _look(engine)
    assert engine.calls == [("stop", LABEL), ("start", LABEL)] and not patrol._engines[URL].kept_alive


def _state() -> str | None:
    return run(patrol.engine_state_of("ses_v"))


def test_a_tab_whose_engine_is_not_handled_is_told_none(engine):
    assert run(patrol.engine_state_of("ses_other")) is None


def test_an_engine_not_looked_at_yet_is_looked_at_once(engine, monkeypatch):
    engine.up = True
    assert _state() == "ready"
    engine.up = False                                                    # not looked at again: the remembered value
    assert _state() == "ready"


def test_the_state_follows_a_wake_and_a_rest(engine, monkeypatch):
    seen = []

    async def watch():
        engine.loop_of[0] = asyncio.get_running_loop()
        service, state = patrol._services()[URL], patrol._engine_of(URL)
        state.up = False
        waking = asyncio.create_task(patrol._wake(service, state, reason="voice_open", warm=True))
        await asyncio.sleep(0.01)
        seen.append(await patrol.engine_state_of("ses_v"))
        await waking
        seen.append(await patrol.engine_state_of("ses_v"))
        resting = asyncio.create_task(patrol._stop(service, state))
        await asyncio.sleep(0)
        seen.append(await patrol.engine_state_of("ses_v"))
        await resting
        seen.append(await patrol.engine_state_of("ses_v"))
    run(watch())
    assert seen == ["waking", "ready", "asleep", "asleep"]


def test_a_failed_wake_is_told_until_the_retry(engine):
    engine.start_failure = "Could not find service"
    patrol.voices_by_conn["conn"] = {"ses_v"}
    _look(engine)
    assert _state() == "failed"
    patrol._engines[URL].failed_at -= patrol.RETRY_SEC
    assert _state() == "asleep"
