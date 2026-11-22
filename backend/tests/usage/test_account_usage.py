"""Which row of the rate-limit log is an account's usage (`backend/usage/account_usage.py`), one case for each kind of
row, and what the reader of the log makes of them (`backend/usage/usage.py`). Run by pytest."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import backend.usage.usage as usage
from backend.usage.account_usage import is_news

NOW = 1_900_000_000
FIVE_RESETS = NOW + 3600
SEVEN_RESETS = NOW + 86400


def usage_row(five: float | None = 40, seven: float | None = 70, *, at: float = NOW, session: str = "quiet",
              five_resets: float | None = FIVE_RESETS, seven_resets: float | None = SEVEN_RESETS) -> dict:
    return {"timestamp": at, "account_id": "work", "session_id": session, "context_pct": 10,
            "five_hour_pct": five, "five_hour_resets_at": None if five is None else five_resets,
            "seven_day_pct": seven, "seven_day_resets_at": None if seven is None else seven_resets}


@pytest.mark.parametrize(("row", "before", "expected"), [
    pytest.param(usage_row(None, None), usage_row(), False, id="no-figure-in-either-window"),
    pytest.param(usage_row(), None, True, id="first-row-with-a-figure"),
    pytest.param(usage_row(41), usage_row(), True, id="another-percentage"),
    pytest.param(usage_row(39), usage_row(), True, id="a-percentage-that-went-down"),
    pytest.param(usage_row(seven_resets=SEVEN_RESETS + 60), usage_row(), True, id="another-reset-time"),
    pytest.param(usage_row(None, at=FIVE_RESETS - 1), usage_row(), True, id="gone-before-its-reset"),
    pytest.param(usage_row(None, at=FIVE_RESETS), usage_row(), False, id="gone-in-the-second-of-its-reset"),
    pytest.param(usage_row(None, at=FIVE_RESETS + 1), usage_row(), False, id="gone-after-its-reset"),
    pytest.param(usage_row(at=NOW + 30), usage_row(), False, id="redrawn"),
])
def test_a_row_is_news_only_when_it_says_something_new(row: dict, before: dict | None, expected: bool) -> None:
    assert is_news(row, before) is expected


@pytest.fixture
def read_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Write the rows to a log and read it as a backend that has just started."""
    path = tmp_path / "rate-limits.jsonl"
    stub = type("Stub", (), {
        "RATE_LIMITS_LOG_PATH": str(path),
        "get_config": staticmethod(lambda: {"accounts": {"work": {}}}),
    })
    monkeypatch.setattr(usage, "_config", stub)

    def read(rows: list[dict]) -> list[dict]:
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        monkeypatch.setattr(usage, "_LATEST", usage._LatestRows())
        return usage.read_all_rate_limits_tail()

    return read


def test_quiet_sessions_redrawing_old_figures_do_not_replace_the_usage(read_log) -> None:
    rows = read_log([
        usage_row(54, 45, at=NOW, session="old"),
        usage_row(84, 49, at=NOW + 10, session="older"),
        usage_row(100, 51, at=NOW + 20, session="working"),
        usage_row(54, 45, at=NOW + 30, session="old"),
        usage_row(84, 49, at=NOW + 40, session="older"),
    ])
    latest = usage.latest_from_tail(rows, account_id="work")
    assert (latest["five_hour_pct"], latest["seven_day_pct"]) == (100, 51)


def test_a_window_the_plan_lost_is_gone_and_is_not_filled_from_an_older_row(read_log) -> None:
    rows = read_log([usage_row(), usage_row(None, at=NOW + 10)])
    latest = usage.latest_from_tail(rows, account_id="work")
    assert latest["five_hour_pct"] is None
    assert latest["five_hour_resets_at"] is None
    assert latest["seven_day_pct"] == 70


def test_a_window_that_only_reset_keeps_its_figure_and_its_passed_time(read_log) -> None:
    rows = read_log([usage_row(), usage_row(None, at=FIVE_RESETS + 10)])
    latest = usage.latest_from_tail(rows, account_id="work")
    assert (latest["five_hour_pct"], latest["five_hour_resets_at"]) == (40, FIVE_RESETS)


def test_a_row_without_a_figure_leaves_the_usage(read_log) -> None:
    rows = read_log([usage_row(), usage_row(None, None, at=NOW + 10, session="starting")])
    assert usage.latest_from_tail(rows, account_id="work")["five_hour_pct"] == 40


def test_the_first_row_of_a_session_is_compared_with_the_usage_of_the_account(read_log) -> None:
    rows = read_log([usage_row(session="working"), usage_row(at=NOW + 10, session="new")])
    assert rows[-1]["timestamp"] == NOW


def test_the_accounts_row_does_not_stand_in_for_the_context_of_a_session(read_log) -> None:
    quiet = {**usage_row(session="quiet"), "context_pct": 80}
    working = {**usage_row(50, session="working", at=NOW + 10), "context_pct": 5}
    rows = read_log([quiet, working])
    latest = usage.latest_from_tail(rows, claude_sid="quiet", account_id="work")
    assert (latest["context_pct"], latest["five_hour_pct"]) == (80, 50)
    assert "session_id" not in rows[-1]
