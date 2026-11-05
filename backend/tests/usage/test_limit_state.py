"""Whether an account is at its usage limit and when that ends (`usage/limit_state.py`)."""
from __future__ import annotations

from backend.usage.limit_state import LimitState, latest_account_row, limit_state

NOW = 1_000_000.0


def _row(account="work", five=50, seven=10, five_resets=NOW + 3600, seven_resets=NOW + 86400, ts=NOW - 5, **extra):
    return {"timestamp": ts, "account_id": account, "five_hour_pct": five, "five_hour_resets_at": five_resets,
            "seven_day_pct": seven, "seven_day_resets_at": seven_resets, **extra}


def test_an_account_below_the_line_is_not_at_the_limit():
    assert limit_state([_row(five=94, seven=10)], "work", 95, NOW) == LimitState(False, NOW - 5, None, None)


def test_either_window_at_the_line_is_the_limit_and_it_ends_when_the_last_of_them_resets():
    state = limit_state([_row(five=95, seven=96, five_resets=NOW + 100, seven_resets=NOW + 900)], "work", 95, NOW)
    assert state.at_limit and state.ends_at == NOW + 900


def test_a_window_that_has_reset_since_the_row_was_written_is_over():
    state = limit_state([_row(five=100, five_resets=NOW - 1)], "work", 95, NOW)
    assert (state.at_limit, state.last_reset, state.ends_at) == (False, NOW - 1, None)


def test_the_line_is_a_parameter():
    rows = [_row(five=97)]
    assert limit_state(rows, "work", 95, NOW).at_limit is True
    assert limit_state(rows, "work", 100, NOW).at_limit is False


def test_only_the_newest_row_of_the_account_counts():
    rows = [_row(five=100), _row("personal", five=10), _row(five=20)]
    assert limit_state(rows, "work", 95, NOW).at_limit is False
    assert latest_account_row(rows, "personal")["five_hour_pct"] == 10


def test_a_row_without_an_account_belongs_to_personal():
    assert limit_state([_row(account=None, five=99)], "personal", 95, NOW).at_limit is True


def test_nothing_is_said_without_a_row_or_a_figure():
    assert limit_state([], "work", 95, NOW) is None
    assert limit_state([_row("personal")], "work", 95, NOW) is None
    assert limit_state([_row(five=None, seven=None)], "work", 95, NOW) is None


def test_a_window_without_a_reset_time_stays_at_the_limit_with_no_end():
    state = limit_state([_row(five=100, five_resets=None)], "work", 95, NOW)
    assert state.at_limit and state.ends_at is None
