"""Two tabs on the `personal` account, whose hold is a line of 70 % of the 7 days on every day, with the pieces the
account hold reads and does replaced: the log of usage, what is read about a tab, the sleep and the message sent."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

import backend.account_hold.hold_continue as hold_continue
import backend.account_hold.hold_patrol as patrol
from backend._common.state import SleepMark, register_session, sessions_meta
from backend.account_fallback.fallback_sensors import TabBreak
from backend.account_fallback.fallback_settings import WEEKDAYS
from backend.tests.limit_samples import use_accounts

LINE_PCT = 70


def usage_row(account="personal", seven=10, five=10, seven_resets=None) -> dict:
    now = time.time()
    return {"timestamp": now - 5, "account_id": account, "five_hour_pct": five, "five_hour_resets_at": now + 3600,
            "seven_day_pct": seven, "seven_day_resets_at": seven_resets if seven_resets is not None else now + 86400}


def accounts(hold_days=None) -> dict:
    return {"personal": {"display_name": "Personal", "env": {},
                         "hold": {"seven_day_at_pct": {day: LINE_PCT for day in WEEKDAYS} if hold_days is None
                                  else hold_days}},
            "work": {"display_name": "Work", "env": {"CLAUDE_CONFIG_DIR": "/nonexistent-work"}}}


@pytest.fixture
def env(monkeypatch, isolated_state):
    """`env.tab` runs on personal (the account with the hold) and `env.other` on work (no hold); `env.rows` is the usage
    log; `env.blocked_by` / `env.stop` say what is read about every tab; `env.sleep_reasons` is what keeps a tab awake
    when it is put to sleep; `env.sent` collects the messages sent and `env.slept` the tabs put to sleep."""
    use_accounts(monkeypatch, accounts())
    monkeypatch.setattr(isolated_state, "save_sessions_meta", lambda: None)
    state = SimpleNamespace(tab=register_session("agent_a", "on personal", account_id="personal"),
                            other=register_session("agent_a", "on work", account_id="work"),
                            rows=[], blocked_by=(), stop=None, sleep_reasons=(), sent=[], slept=[], deliver=True)
    monkeypatch.setattr(patrol, "save_sessions_meta", lambda: None)
    monkeypatch.setattr(hold_continue, "save_sessions_meta", lambda: None)
    for module in (patrol, hold_continue):
        monkeypatch.setattr(module, "read_all_rate_limits_tail", lambda: state.rows)
    monkeypatch.setattr(patrol, "read_tab_break", lambda _sid: TabBreak(state.stop, state.blocked_by))

    async def _sleep(session_id, *, stopped_by_limit=False):
        state.slept.append((session_id, stopped_by_limit))
        if state.sleep_reasons:
            return state.sleep_reasons
        sessions_meta[session_id].sleep = SleepMark(claude_sid="c1", record="/record.jsonl", slept_at=1)
        return ()

    async def _send(session_id, text):
        state.sent.append((session_id, text))
        return state.deliver

    monkeypatch.setattr(patrol, "sleep_at_break", _sleep)
    for module in (patrol, hold_continue):
        monkeypatch.setattr(module, "send_to_tab", _send)
    return state
