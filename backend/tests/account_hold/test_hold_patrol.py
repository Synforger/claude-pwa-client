"""The account hold patrol stops the tabs of an account at its line and leaves them stopped (`hold_patrol.py`). The
usage log, what is read about a tab, the sleep and the message sent are the fixture's."""
from __future__ import annotations

import logging

from backend.account_hold import hold_patrol as patrol
from backend.account_hold.hold_envelope import CONTINUE, STOP
from backend.jsonl.jsonl_predicates import CLIENT_NOTICE_OPENING
from backend.sleep.sleep_judgement import PROCESSES_RUNNING, TURN_OPEN
from backend.sleep.record_facts import LimitStop
from backend.tests.account_hold.conftest import accounts, usage_row
from backend.tests.async_run import run
from backend.tests.limit_samples import use_accounts


def test_a_tab_on_the_account_over_its_line_is_put_to_sleep_at_a_break_and_marked(env, caplog):
    env.rows = [usage_row(seven=70)]
    caplog.set_level(logging.INFO, logger=patrol.logger.name)
    assert run(patrol.tick()) == [env.tab.id]
    assert env.slept == [(env.tab.id, False)]
    assert env.tab.sleep is not None and env.tab.held_at is not None
    assert f"account hold: held session={env.tab.id} account=personal" in caplog.text
    assert env.sent == []                                  # at a break it is stopped without a word


def test_a_tab_stays_while_the_usage_is_under_the_line(env):
    env.rows = [usage_row(seven=69)]
    assert run(patrol.tick()) == [] and env.slept == [] and env.tab.held_at is None


def test_the_5_hours_do_not_stop_a_tab_without_a_line_of_their_own(env):
    env.rows = [usage_row(five=100, seven=10)]
    assert run(patrol.tick()) == [] and env.slept == []


def test_a_tab_is_put_to_sleep_when_the_5_hours_are_at_their_line(env, monkeypatch, caplog):
    use_accounts(monkeypatch, accounts(five_hour_at_pct=95))
    env.rows = [usage_row(five=94, seven=10)]
    assert run(patrol.tick()) == [] and env.slept == []
    env.rows = [usage_row(five=95, seven=10)]
    caplog.set_level(logging.INFO, logger=patrol.logger.name)
    assert run(patrol.tick()) == [env.tab.id]
    assert env.tab.held_at is not None and f"account hold: held session={env.tab.id} account=personal" in caplog.text


def test_a_tab_is_stopped_by_the_5_hours_on_a_day_whose_7_days_have_no_line(env, monkeypatch):
    use_accounts(monkeypatch, accounts(hold_days={}, five_hour_at_pct=95))
    env.rows = [usage_row(five=96, seven=100)]
    assert run(patrol.tick()) == [env.tab.id]


def test_a_5_hours_window_that_has_reset_does_not_stop_a_tab(env, monkeypatch):
    use_accounts(monkeypatch, accounts(five_hour_at_pct=95))
    usage = usage_row(five=99, seven=10)
    usage["five_hour_resets_at"] = usage["timestamp"] - 60
    env.rows = [usage]
    assert run(patrol.tick()) == [] and env.slept == []


def test_a_pinned_tab_is_not_stopped_by_the_5_hours_either(env, monkeypatch):
    use_accounts(monkeypatch, accounts(five_hour_at_pct=95))
    env.tab.account_pinned = True
    env.rows = [usage_row(five=99, seven=10)]
    assert run(patrol.tick()) == [] and env.slept == []


# --- a tab the fallback of another account moved here ---

def test_a_tab_moved_here_is_not_stopped_while_the_account_it_belongs_to_is_clear_of_its_line(env, monkeypatch):
    use_accounts(monkeypatch, accounts(five_hour_at_pct=95, work_fallback=95))
    env.tab.fallback_from = "work"
    env.rows = [usage_row("work", five=10), usage_row(five=96, seven=10)]
    assert run(patrol.tick()) == [] and env.slept == [] and env.tab.held_at is None


def test_a_tab_moved_here_is_stopped_when_the_account_it_belongs_to_is_at_its_line_too(env, monkeypatch):
    use_accounts(monkeypatch, accounts(five_hour_at_pct=95, work_fallback=95))
    env.tab.fallback_from = "work"
    env.rows = [usage_row("work", five=95), usage_row(five=96, seven=10)]
    assert run(patrol.tick()) == [env.tab.id]


def test_a_tab_moved_here_is_stopped_when_the_usage_of_the_account_it_belongs_to_is_not_known(env, monkeypatch):
    use_accounts(monkeypatch, accounts(five_hour_at_pct=95, work_fallback=95))
    env.tab.fallback_from = "work"
    env.rows = [usage_row(five=96, seven=10)]
    assert run(patrol.tick()) == [env.tab.id]


def test_a_tab_moved_here_that_is_not_to_be_stopped_is_not_asked_to_come_to_a_break_either(env, monkeypatch):
    use_accounts(monkeypatch, accounts(five_hour_at_pct=95, work_fallback=95))
    env.tab.fallback_from = "work"
    env.blocked_by = (TURN_OPEN,)
    env.rows = [usage_row("work", five=10), usage_row(seven=90)]
    assert run(patrol.tick()) == [] and env.sent == [] and env.tab.hold_asked_at is None


def test_a_tab_of_an_account_without_a_hold_is_left_alone_whatever_its_usage(env):
    env.rows = [usage_row(account="work", seven=100), usage_row(seven=10)]
    assert run(patrol.tick()) == [] and env.other.held_at is None and env.slept == []


def test_a_tab_pinned_to_its_account_is_not_stopped(env):
    env.tab.account_pinned = True
    env.rows = [usage_row(seven=90)]
    assert run(patrol.tick()) == [] and env.slept == [] and env.tab.held_at is None


def test_a_tab_that_is_asleep_already_is_not_marked(env):
    from backend._common.state import SleepMark
    env.tab.sleep = SleepMark(claude_sid="c0", record="/r.jsonl", slept_at=1)
    env.rows = [usage_row(seven=90)]
    assert run(patrol.tick()) == [] and env.slept == [] and env.tab.held_at is None


def test_a_tab_moved_here_by_the_fallback_of_another_account_runs_here_and_is_stopped(env):
    env.tab.fallback_from = "work"
    env.rows = [usage_row(seven=90)]
    assert run(patrol.tick()) == [env.tab.id]


def test_a_tab_that_keeps_answering_is_asked_once_to_come_to_a_break_then_stopped_when_it_does(env, caplog):
    env.rows = [usage_row(seven=90)]
    env.blocked_by = (TURN_OPEN,)
    caplog.set_level(logging.INFO, logger=patrol.logger.name)
    assert run(patrol.tick()) == [] and env.slept == []
    [(session_id, text)] = env.sent
    assert session_id == env.tab.id and text.splitlines()[0] == CLIENT_NOTICE_OPENING
    assert f'<account-hold phase="{STOP}" account="personal">' in text and "Personal" in text
    assert env.tab.hold_asked_at is not None
    assert f"account hold: asked to stop session={env.tab.id} account=personal" in caplog.text
    run(patrol.tick())
    assert len(env.sent) == 1                              # not a second request during this stay above the line
    env.blocked_by = ()
    assert run(patrol.tick()) == [env.tab.id]
    assert env.tab.held_at is not None and env.tab.hold_asked_at is None


def test_a_tab_held_only_by_what_it_runs_is_not_asked(env):
    env.rows = [usage_row(seven=90)]
    env.blocked_by = (PROCESSES_RUNNING,)
    assert run(patrol.tick()) == [] and env.sent == [] and env.slept == []


def test_a_request_that_was_not_delivered_is_made_again_at_the_next_look(env):
    env.rows = [usage_row(seven=90)]
    env.blocked_by = (TURN_OPEN,)
    env.deliver = False
    run(patrol.tick())
    assert env.tab.hold_asked_at is None
    env.deliver = True
    run(patrol.tick())
    assert len(env.sent) == 2 and env.tab.hold_asked_at is not None


def test_the_request_is_forgotten_when_the_usage_goes_under_the_line(env):
    env.rows = [usage_row(seven=90)]
    env.blocked_by = (TURN_OPEN,)
    run(patrol.tick())
    env.rows = [usage_row(seven=10)]
    run(patrol.tick())
    assert env.tab.hold_asked_at is None


def test_a_tab_the_limit_stopped_is_put_to_sleep_as_one_the_limit_stopped(env):
    env.rows = [usage_row(seven=100)]
    env.stop = LimitStop("lim1", 1.0)
    assert run(patrol.tick()) == [env.tab.id] and env.slept == [(env.tab.id, True)]


def test_a_tab_the_sleep_refuses_is_not_marked_and_is_looked_at_again(env):
    env.rows = [usage_row(seven=90)]
    env.sleep_reasons = ("processes_running",)
    assert run(patrol.tick()) == [] and env.tab.held_at is None and env.tab.sleep is None
    env.sleep_reasons = ()
    assert run(patrol.tick()) == [env.tab.id]


def test_a_stopped_tab_stays_stopped_when_the_usage_falls_and_nothing_continues_it(env):
    env.rows = [usage_row(seven=90)]
    run(patrol.tick())
    env.rows = [usage_row(seven=5)]                        # a reset, or a day without a line
    assert run(patrol.tick()) == []
    assert env.tab.held_at is not None and env.tab.sleep is not None and env.sent == []


def test_a_message_that_wakes_a_stopped_tab_takes_the_mark_off(env, caplog):
    env.rows = [usage_row(seven=90)]
    run(patrol.tick())
    env.tab.sleep = None                                    # the sleep patrol clears its mark once the claude runs again
    env.rows = [usage_row(seven=5)]
    caplog.set_level(logging.INFO, logger=patrol.logger.name)
    run(patrol.tick())
    assert env.tab.held_at is None
    assert f"account hold: released session={env.tab.id} account=personal woken=1" in caplog.text


def test_a_tab_woken_while_the_usage_is_still_over_the_line_is_stopped_again_at_its_next_break(env):
    env.rows = [usage_row(seven=90)]
    run(patrol.tick())
    env.tab.sleep = None
    assert run(patrol.tick()) == [env.tab.id] and env.tab.held_at is not None and len(env.slept) == 2


def test_nothing_is_read_when_no_account_has_a_hold_and_no_tab_is_marked(env, monkeypatch):
    from backend.tests.account_hold.conftest import accounts
    from backend.tests.limit_samples import use_accounts
    use_accounts(monkeypatch, {name: {k: v for k, v in entry.items() if k != "hold"}
                               for name, entry in accounts().items()})
    monkeypatch.setattr(patrol, "read_all_rate_limits_tail", lambda: (_ for _ in ()).throw(AssertionError("read")))
    assert run(patrol.tick()) == []


def test_the_message_that_continues_a_tab_has_its_own_phase_and_the_clients_first_line():
    from backend.account_hold.hold_envelope import continue_envelope
    text = continue_envelope("personal")
    assert text.splitlines()[0] == CLIENT_NOTICE_OPENING
    assert f'<account-hold phase="{CONTINUE}" account="personal">' in text
