"""The patrols walk `sessions_meta`, and an API tab is not in it (`backend/api_tabs/`): one pass of each patrol that moves,
stops, sleeps, hands over or watches tabs finds nothing to do for the API tab, and leaves the table as it was."""
from __future__ import annotations

import dataclasses

import pytest

import backend.account_fallback.fallback_patrol as fallback
import backend.account_hold.hold_patrol as hold
import backend.child_watch.watch_patrol as watch
import backend.limit_resume.resume_patrol as resume
import backend.rollover.rollover as rollover
import backend.sleep.sleep_patrol as sleep
import backend.usage.usage as usage_log
from backend._common import state as state_mod
from backend.api_tabs import current_table
from backend.sleep import sleep_judgement
from backend.sleep.record_facts import RecordFacts
from backend.tests.api_tabs.samples import TAB_ID
from backend.tests.async_run import run


# a tab whose claude is up and answering (= the sleep patrol's own sample, kept here so this file stands alone)
AWAKE = sleep_judgement.SleepFacts(
    claude_running=True, starting=False, turn_open=False, record_found=True, quiet_minutes=0.0, context_pct=20,
    rollover_idle_pct=40, foreign_processes=(), record=RecordFacts(), on_voice_call=False, rollover_asks=0,
    answered_since_start=True, account_pending=False,
)


@pytest.fixture
def looked_at(api_env, isolated_state, monkeypatch):
    """Every tab id a patrol asked about, with the usage log read from an empty list. The patrols read only
    `sessions_meta`, so the API tab is in none of the lists they walk."""
    seen: list[str] = []
    for module in (fallback, hold, resume):
        monkeypatch.setattr(module, "read_all_rate_limits_tail", lambda: [])
    monkeypatch.setattr(usage_log, "read_all_rate_limits_tail", lambda: [])
    monkeypatch.setattr(fallback, "_look", _recording(seen, fallback._look))
    monkeypatch.setattr(resume, "_look", _recording(seen, resume._look))
    monkeypatch.setattr(watch, "_look", _recording(seen, watch._look))
    claude = isolated_state.register_session("agent_a", title="a Claude tab")
    monkeypatch.setattr(isolated_state, "save_sessions_meta", lambda: None)
    return seen, claude


def _recording(seen: list[str], inner):
    async def look(session_id, *args):
        seen.append(session_id)
        return await inner(session_id, *args)
    return look


@pytest.mark.parametrize(("module", "asked"), [(fallback, False), (resume, True), (watch, True)],
                         ids=["account fallback", "limit resume", "child watch"])
def test_a_pass_of_a_patrol_never_looks_at_the_api_tab(looked_at, module, asked):
    seen, claude = looked_at
    assert current_table().tab(TAB_ID) is not None                 # the API tab exists, in a table of its own
    assert run(module.tick()) == []
    assert TAB_ID not in seen
    assert seen == ([claude.id] if asked else [])                  # the account fallback has no line declared: no look
    assert TAB_ID not in state_mod.sessions_meta


def test_the_sleep_patrol_puts_the_quiet_claude_tab_to_sleep_and_never_asks_about_the_api_tab(looked_at, monkeypatch):
    _seen, claude = looked_at
    asked: list[str] = []

    def facts_of(sid, *_args):
        asked.append(sid)
        return dataclasses.replace(AWAKE, quiet_minutes=1000.0)

    async def put_to_sleep(sid, _minutes, **_flags):
        slept.append(sid)
        return True

    async def not_short_of_memory():
        return False

    slept: list[str] = []
    monkeypatch.setattr(sleep, "sleep_minutes", lambda _sid: 60)
    monkeypatch.setattr(sleep, "pressure_minutes", lambda _sid: None)
    monkeypatch.setattr(sleep, "_has_reported", lambda _meta: False)
    monkeypatch.setattr(sleep, "gather", facts_of)
    monkeypatch.setattr(sleep, "put_to_sleep", put_to_sleep)
    monkeypatch.setattr(sleep, "_short_of_memory", not_short_of_memory)
    assert run(sleep.tick()) == [claude.id] and slept == [claude.id] and asked == [claude.id]


def test_the_hold_patrol_and_the_rollover_have_nothing_to_do_for_it(looked_at):
    assert run(hold.tick()) == []                                   # no line is declared
    assert run(rollover.tick()) is None                             # no condition is declared
    assert TAB_ID not in state_mod.sessions_meta and TAB_ID not in state_mod.agent_status
