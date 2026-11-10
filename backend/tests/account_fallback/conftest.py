"""A tab on the `work` account whose fallback is `personal`, with the pieces the account fallback reads and does
replaced: the log of usage, what is read about the tab, and the message it is sent. The move itself is the real one."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

import backend._common.config as config
import backend.account_fallback.fallback_patrol as patrol
from backend.account_fallback.fallback_judgement import PROMPT_CACHE_LIFETIME_MIN
from backend.account_fallback.fallback_sensors import TabBreak
from backend.sleep.record_facts import LimitStop
from backend.tests.fork.test_fork import _setup_account_move
from backend.tests.limit_samples import lines_of, stopped_mid_turn, use_accounts


def usage_row(account="work", five=10, seven=10, five_resets=None, seven_resets=None, ts=None) -> dict:
    now = time.time()
    return {"timestamp": ts if ts is not None else now - 5, "account_id": account, "five_hour_pct": five,
            "five_hour_resets_at": five_resets if five_resets is not None else now + 3600, "seven_day_pct": seven,
            "seven_day_resets_at": seven_resets if seven_resets is not None else now + 86400}


def accounts_with_fallback(at_pct=95, ahead_pct=None, personal_hold=None) -> dict:
    """The accounts of the fixture: `work` falls back to `personal`. `ahead_pct` is the width of the fallback ahead of
    its line (the key is left out without it), `personal_hold` the `hold` of `personal` (left out without it)."""
    fallback = {"to": "personal", "at_pct": at_pct, **({} if ahead_pct is None else {"ahead_pct": ahead_pct})}
    personal = {"display_name": "Personal", "env": {}, **({} if personal_hold is None else {"hold": personal_hold})}
    return {"personal": personal,
            "work": {"display_name": "Work", "env": {"CLAUDE_CONFIG_DIR": "/nonexistent-work"}, "fallback": fallback}}


@pytest.fixture
def env(tmp_path, monkeypatch, isolated_state):
    """`env.tab` runs on work; `env.rows` is the usage log; `env.stop` / `env.blocked_by` / `env.owed` say what is read about the tab
    (a stop leaves its continuation owed); `env.quiet_minutes` the fact its
    cache is judged cold from (`env.cold()` makes it quiet for the cache's lifetime);
    `env.sent` collects the messages sent to tabs; `env.events` the stops and spawns of the tab's claude."""
    sessions_mod, tab, src, work_dir, events = _setup_account_move(
        tmp_path, monkeypatch, isolated_state, lines_of(stopped_mid_turn()))
    tab.account_id = "work"
    use_accounts(monkeypatch, accounts_with_fallback())
    monkeypatch.setattr(config, "CLAUDE_PROJECTS_DIRS", [src.parent.parent, work_dir.parent], raising=False)
    state = SimpleNamespace(tab=tab, src=src, work_dir=work_dir, events=events, rows=[], stop=None, blocked_by=(),
                            owed=None, sent=[], tmp_path=tmp_path, quiet_minutes=0)
    monkeypatch.setattr(patrol, "read_all_rate_limits_tail", lambda: state.rows)
    monkeypatch.setattr(patrol, "read_tab_break",
                        lambda _sid: TabBreak(state.stop, state.blocked_by, owed=state.owed or state.stop,
                                              quiet_minutes=state.quiet_minutes))

    async def _send(session_id, text):
        state.sent.append((session_id, text))
        return True
    monkeypatch.setattr(patrol, "send_to_tab", _send)
    state.stopped = lambda: setattr(state, "stop", LimitStop("lim1", time.time() - 30))
    state.cold = lambda: setattr(state, "quiet_minutes", PROMPT_CACHE_LIFETIME_MIN)
    return state
