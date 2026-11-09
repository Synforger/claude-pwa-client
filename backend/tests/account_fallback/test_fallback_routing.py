"""The account fallback moves the tabs whose cache is cold ahead of the line, brings them back when the account is clear
and their cache is cold, and brings them back at once when the account they run on has reached its own line
(`fallback_patrol.py`). The move is the real one; the usage log, what is read about the tab and the message sent are the
fixture's."""
from __future__ import annotations

import logging
import time

import pytest

import backend.account_fallback.fallback_patrol as patrol
from backend._common.state import SleepMark
from backend.account_fallback.fallback_envelope import PAUSE
from backend.tests.account_fallback.conftest import accounts_with_fallback, usage_row
from backend.tests.async_run import run
from backend.tests.limit_samples import use_accounts

PERSONAL_HOLD = {"five_hour_at_pct": 95, "seven_day_at_pct": {day: 70 for day in
                                                            ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}}


@pytest.fixture
def ahead(env, monkeypatch):
    """The fallback of work moves its tabs 5 points ahead of its line of 95 %."""
    use_accounts(monkeypatch, accounts_with_fallback(ahead_pct=5))
    return env


@pytest.fixture
def held(env, monkeypatch):
    """Like `ahead`, and personal stops its tabs at 95 % of its 5 hours or 70 % of its 7 days."""
    use_accounts(monkeypatch, accounts_with_fallback(ahead_pct=5, personal_hold=PERSONAL_HOLD))
    return env


def _moved(env):
    env.rows = [usage_row(five=100)]
    run(patrol.tick())
    assert env.tab.fallback_from == "work"
    env.events.clear()
    env.sent.clear()


def _sleeping_on_personal(env):
    env.tab.sleep = SleepMark(claude_sid="OLD", record=str(env.src), slept_at=int(time.time()), account_id="personal")


def _messages(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records]


# --- moving ahead of the line ---

def test_a_tab_with_a_warm_cache_is_not_moved_ahead_of_the_line(ahead):
    ahead.rows = [usage_row(five=92)]
    assert run(patrol.tick()) == [] and ahead.tab.account_id == "work"


@pytest.mark.parametrize("cold, why", [
    (lambda env: env.cold(), "quiet"),
    (lambda env: (setattr(env, "context_pct", 45), setattr(env, "rollover_idle_pct", 40)), "context_at_rollover_line"),
])
def test_a_tab_with_a_cold_cache_is_moved_ahead_of_the_line(ahead, caplog, cold, why):
    ahead.rows = [usage_row(five=92)]
    cold(ahead)
    with caplog.at_level(logging.INFO):
        assert run(patrol.tick()) == [ahead.tab.id]
    assert (ahead.tab.account_id, ahead.tab.fallback_from) == ("personal", "work")
    assert f"account fallback: moved ahead session={ahead.tab.id} from=work to=personal cold={why}" in _messages(caplog)
    assert ahead.sent == []                                          # it was at a break: nothing to carry on from


def test_a_tab_is_moved_ahead_by_the_7_days_too(ahead):
    ahead.rows = [usage_row(five=10, seven=91)]
    ahead.cold()
    assert run(patrol.tick()) == [ahead.tab.id]


def test_a_tab_is_not_moved_before_the_width_ahead_of_the_line(ahead):
    ahead.rows = [usage_row(five=89, seven=89)]
    ahead.cold()
    assert run(patrol.tick()) == [] and ahead.tab.account_id == "work"


def test_without_a_width_a_cold_tab_waits_for_the_line_like_any_tab(env):
    env.rows = [usage_row(five=94)]
    env.cold()
    assert run(patrol.tick()) == [] and env.tab.account_id == "work"
    env.rows = [usage_row(five=95)]
    assert run(patrol.tick()) == [env.tab.id]


def test_a_tab_that_is_not_at_a_break_is_not_moved_ahead_and_is_not_asked_to_come_to_one(ahead):
    ahead.rows = [usage_row(five=92)]
    ahead.cold()
    ahead.blocked_by = ("turn_open",)
    assert run(patrol.tick()) == [] and ahead.tab.account_id == "work" and ahead.sent == []
    assert ahead.tab.pause_asked_at is None


def test_a_tab_that_keeps_answering_at_the_line_is_still_asked(ahead):
    ahead.rows = [usage_row(five=95)]
    ahead.blocked_by = ("turn_open",)
    run(patrol.tick())
    assert [text for _sid, text in ahead.sent if f'phase="{PAUSE}"' in text and "移します" in text]


def test_a_tab_is_not_moved_ahead_to_an_account_that_is_at_its_own_line_and_the_log_says_why_once(held, caplog):
    held.rows = [usage_row(five=92), usage_row("personal", five=96)]
    held.cold()
    with caplog.at_level(logging.INFO):
        assert run(patrol.tick()) == [] and run(patrol.tick()) == []
    assert held.tab.account_id == "work"
    said = [m for m in _messages(caplog) if "not moved ahead of the line" in m]
    assert said == [f"account fallback: not moved ahead of the line because personal is at its line "
                    f"session={held.tab.id} account=work"]


def test_a_tab_at_the_line_is_moved_even_when_the_account_it_moves_to_is_at_its_own_line(held):
    held.rows = [usage_row(five=100), usage_row("personal", five=96)]
    assert run(patrol.tick()) == [held.tab.id]


def test_a_tab_asleep_is_moved_ahead_of_the_line_when_it_is_woken(ahead):
    ahead.tab.sleep = SleepMark(claude_sid="OLD", record=str(ahead.src), slept_at=int(time.time()), account_id="work")
    ahead.rows = [usage_row(five=92)]
    assert run(patrol.tick()) == []                                  # the patrol never wakes it
    run(patrol.move_before_wake(ahead.tab.id))
    assert (ahead.tab.account_id, ahead.tab.fallback_from) == ("personal", "work")


def test_a_tab_asleep_wakes_where_it_slept_while_the_account_is_clear_of_the_width_ahead(ahead):
    ahead.tab.sleep = SleepMark(claude_sid="OLD", record=str(ahead.src), slept_at=int(time.time()), account_id="work")
    ahead.rows = [usage_row(five=89)]
    run(patrol.move_before_wake(ahead.tab.id))
    assert ahead.tab.account_id == "work" and ahead.events == []


# --- coming back ---

def test_a_moved_tab_that_works_is_not_brought_back_and_the_log_says_it_returns_when_cold_once(ahead, caplog):
    _moved(ahead)
    ahead.rows = [usage_row(five=10)]
    with caplog.at_level(logging.INFO):
        assert run(patrol.tick()) == [] and run(patrol.tick()) == []
    assert ahead.tab.account_id == "personal"
    said = [m for m in _messages(caplog) if "returns when cold" in m]
    assert said == [f"account fallback: returns when cold session={ahead.tab.id} account=personal home=work"]


def test_a_moved_tab_comes_back_when_its_cache_has_gone_cold(ahead, caplog):
    _moved(ahead)
    ahead.rows = [usage_row(five=10)]
    ahead.cold()
    with caplog.at_level(logging.INFO):
        assert run(patrol.tick()) == [ahead.tab.id]
    assert (ahead.tab.account_id, ahead.tab.fallback_from) == ("work", None)
    assert any(m.startswith(f"account fallback: returned session={ahead.tab.id} from=personal to=work cold=quiet")
               for m in _messages(caplog))


def test_a_moved_tab_comes_back_when_its_context_is_at_the_line_where_the_rollover_takes_it_over(ahead):
    _moved(ahead)
    ahead.rows = [usage_row(five=10)]
    ahead.context_pct, ahead.rollover_idle_pct = 41, 40
    assert run(patrol.tick()) == [ahead.tab.id] and ahead.tab.account_id == "work"


def test_a_moved_tab_stays_while_the_account_is_within_the_width_ahead_of_its_line_even_when_cold(ahead):
    _moved(ahead)
    ahead.cold()
    ahead.rows = [usage_row(five=92)]
    assert run(patrol.tick()) == [] and ahead.tab.account_id == "personal"
    ahead.rows = [usage_row(five=89)]
    assert run(patrol.tick()) == [ahead.tab.id]


def test_a_tab_moved_ahead_does_not_go_back_and_forth_while_the_account_stays_near_its_line(ahead):
    ahead.rows = [usage_row(five=92)]
    ahead.cold()
    assert run(patrol.tick()) == [ahead.tab.id]
    ahead.cold()                                                    # still cold, as far as the sensor can tell
    assert run(patrol.tick()) == [] and run(patrol.tick()) == [] and ahead.tab.account_id == "personal"


def test_a_moved_tab_comes_back_at_a_break_only(ahead):
    _moved(ahead)
    ahead.rows = [usage_row(five=10)]
    ahead.cold()
    ahead.blocked_by = ("awaiting_tool_result",)
    assert run(patrol.tick()) == [] and ahead.tab.account_id == "personal"
    ahead.blocked_by = ()
    assert run(patrol.tick()) == [ahead.tab.id]


def test_a_sleeping_tab_on_the_fallback_account_goes_back_when_it_is_woken_while_its_account_is_clear(ahead, caplog):
    _moved(ahead)
    _sleeping_on_personal(ahead)
    ahead.rows = [usage_row(five=10)]
    assert run(patrol.tick()) == []                                  # the patrol never wakes it
    with caplog.at_level(logging.INFO):
        run(patrol.move_before_wake(ahead.tab.id))
    assert (ahead.tab.account_id, ahead.tab.fallback_from, ahead.tab.fallback_copy) == ("work", None, None)
    assert ahead.events == [f"kill {ahead.tab.id}", f"spawn {ahead.tab.id}"]
    assert f"account fallback: returned session={ahead.tab.id} from=personal to=work asleep=1" in _messages(caplog)


def test_a_sleeping_tab_on_the_fallback_account_stays_when_it_is_woken_while_its_account_is_near_its_line(ahead):
    _moved(ahead)
    _sleeping_on_personal(ahead)
    ahead.rows = [usage_row(five=92)]
    run(patrol.move_before_wake(ahead.tab.id))
    assert ahead.tab.account_id == "personal" and ahead.events == []


# --- the account the tab runs on reaches its own line ---

def test_a_moved_tab_with_a_warm_cache_comes_back_at_once_when_the_account_it_runs_on_is_at_a_line(held, caplog):
    _moved(held)
    held.rows = [usage_row(five=10), usage_row("personal", five=95)]
    with caplog.at_level(logging.INFO):
        assert run(patrol.tick()) == [held.tab.id]
    assert (held.tab.account_id, held.tab.fallback_from) == ("work", None)
    assert any(m.startswith(f"account fallback: back because personal is at its line session={held.tab.id} "
                            f"from=personal to=work") for m in _messages(caplog))


def test_the_7_days_of_the_account_it_runs_on_bring_it_back_too(held):
    _moved(held)
    held.rows = [usage_row(five=10), usage_row("personal", five=10, seven=70)]
    assert run(patrol.tick()) == [held.tab.id] and held.tab.account_id == "work"


def test_the_account_it_runs_on_just_under_its_lines_does_not_bring_it_back(held):
    _moved(held)
    held.rows = [usage_row(five=10), usage_row("personal", five=94, seven=69)]
    assert run(patrol.tick()) == [] and held.tab.account_id == "personal"


def test_a_moved_tab_stays_when_both_accounts_are_at_their_lines(held):
    _moved(held)
    held.rows = [usage_row(five=100), usage_row("personal", five=96)]
    assert run(patrol.tick()) == [] and held.tab.account_id == "personal"


def test_a_moved_tab_stays_when_the_usage_of_the_account_it_belongs_to_is_not_known(held):
    _moved(held)
    held.rows = [usage_row("personal", five=96)]
    assert run(patrol.tick()) == [] and held.tab.account_id == "personal"


def test_the_account_it_belongs_to_only_near_its_line_is_not_at_it_so_the_tab_goes_back(held):
    _moved(held)
    held.rows = [usage_row(five=92), usage_row("personal", five=96)]
    assert run(patrol.tick()) == [held.tab.id] and held.tab.account_id == "work"


def test_a_tab_that_keeps_answering_is_asked_to_come_to_a_break_to_go_back_and_told_to_carry_on_after(held):
    _moved(held)
    held.rows = [usage_row(five=10), usage_row("personal", five=96)]
    held.blocked_by = ("turn_open",)
    assert run(patrol.tick()) == [] and run(patrol.tick()) == []
    asks = [text for _sid, text in held.sent if f'phase="{PAUSE}"' in text]
    assert len(asks) == 1 and "戻します" in asks[0] and 'from="personal" to="work"' in asks[0]
    assert held.tab.pause_asked_at is not None
    held.blocked_by = ()
    held.sent.clear()
    assert run(patrol.tick()) == [held.tab.id] and held.tab.account_id == "work"
    assert held.tab.pause_asked_at is None
    assert len(held.sent) == 1 and f'reason="{PAUSE}"' in held.sent[0][1]


def test_a_sleeping_tab_goes_back_when_it_is_woken_while_the_account_it_runs_on_is_at_its_line(held, caplog):
    _moved(held)
    _sleeping_on_personal(held)
    held.rows = [usage_row(five=10), usage_row("personal", five=96)]
    with caplog.at_level(logging.INFO):
        run(patrol.move_before_wake(held.tab.id))
    assert (held.tab.account_id, held.tab.fallback_from) == ("work", None)
    assert any(m.startswith(f"account fallback: back because personal is at its line session={held.tab.id}")
               for m in _messages(caplog))


def test_a_pinned_tab_that_runs_elsewhere_still_goes_back_without_waiting_for_the_cache(held):
    _moved(held)
    held.tab.account_pinned = True
    held.rows = [usage_row(five=100)]
    assert run(patrol.tick()) == [held.tab.id] and held.tab.account_id == "work"
