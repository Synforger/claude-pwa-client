"""The marks that say a ticket needs another look, tried at their edges with the day and the time passed in, and the pieces of a
tab's own list of tickets that need no file: where a ticket came from, its last line, its next step and whether the tab wrote."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from backend.tickets import ticket_view

TODAY = date(2026, 11, 21)
NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


def _ago(**span) -> str:
    return (NOW - timedelta(**span)).isoformat(timespec="milliseconds")


def _marks(status: str, *, due: str | None = None, last: str = "") -> list[str]:
    return ticket_view.marks(status, due, last, TODAY, NOW)


# --- the due day ---


@pytest.mark.parametrize("due, expected", [
    ("2026-11-19", ["overdue"]), ("2026-11-20", ["overdue"]),
    ("2026-11-21", ["due_soon"]), ("2026-11-22", ["due_soon"]), ("2026-11-23", ["due_soon"]),
    ("2026-11-24", []), (None, []),
])
def test_a_due_day_before_today_is_overdue_and_one_within_two_days_of_today_is_due_soon(due, expected):
    assert _marks("open", due=due) == expected


def test_a_due_day_that_is_not_a_day_gives_no_mark():
    assert _marks("open", due="soon") == []


def test_the_due_day_is_compared_with_the_day_passed_in_and_not_with_the_moment():
    late = datetime(2026, 11, 21, 23, 59, tzinfo=timezone.utc)
    assert ticket_view.marks("open", "2026-11-21", "", TODAY, late) == ["due_soon"]


# --- the age of the last line ---


def test_a_waiting_ticket_is_stale_on_the_fifth_day_and_not_a_second_before():
    assert _marks("waiting", last=_ago(days=5)) == ["waiting_stale"]
    assert _marks("waiting", last=_ago(days=5, seconds=-1)) == []
    assert _marks("waiting", last=_ago(days=30)) == ["waiting_stale"]


def test_an_open_ticket_is_idle_on_the_fourteenth_day_and_not_a_second_before():
    assert _marks("open", last=_ago(days=14)) == ["idle"]
    assert _marks("open", last=_ago(days=14, seconds=-1)) == []


def test_an_open_ticket_is_not_stale_and_a_waiting_one_is_not_idle():
    assert _marks("open", last=_ago(days=6)) == []
    assert _marks("waiting", last=_ago(days=15)) == ["waiting_stale"]


def test_without_the_time_of_a_line_a_tab_wrote_no_age_mark_is_given():
    assert _marks("open", last="") == [] and _marks("waiting", last="not a time") == []


def test_the_age_is_counted_from_a_time_written_with_z_as_well_as_with_an_offset():
    assert _marks("open", last="2026-11-07T12:00:00.000Z") == ["idle"]
    assert _marks("open", last="2026-11-07T21:00:00.000+09:00") == ["idle"]


# --- more than one mark, and the states that take fewer ---


def test_every_mark_that_fits_is_given_in_the_order_overdue_due_soon_waiting_stale_idle():
    assert _marks("open", due="2026-11-01", last=_ago(days=20)) == ["overdue", "idle"]
    assert _marks("waiting", due="2026-11-22", last=_ago(days=9)) == ["due_soon", "waiting_stale"]


def test_a_ticket_that_waits_for_the_operator_has_the_two_due_marks_and_no_age_mark():
    assert _marks("waiting-operator", due="2026-11-01", last=_ago(days=90)) == ["overdue"]
    assert _marks("waiting-operator", last=_ago(days=90)) == []


def test_a_closed_ticket_has_no_mark():
    assert _marks("closed", due="2026-01-01", last=_ago(days=90)) == []


# --- the pieces of a tab's own list ---


def _line(kind: str, at: str, tab: str = "", text: str = "", **extra) -> dict:
    return {"kind": kind, "at": at, "tab": tab, "text": text, **extra}


def test_the_last_time_a_tab_wrote_does_not_count_the_lines_the_client_writes():
    entries = [_line("opened", "1", "ses_a", "r"), _line("answered", "2"), _line("delivered", "3"), _line("seen", "4")]
    assert ticket_view.last_tab_time(entries) == "1"
    assert ticket_view.last_tab_time([_line("answered", "2")]) == "" and ticket_view.last_tab_time([]) == ""


def test_the_next_step_is_the_first_line_of_the_last_line_a_tab_wrote_that_has_text():
    entries = [_line("opened", "1", "ses_a", "request"), _line("added", "2", "ses_b", "first\nsecond"), _line("passed", "3", "ses_b"),
               _line("answered", "4", "", "client text")]
    assert ticket_view.latest_tab_line(entries) is entries[1]
    assert ticket_view.first_line(entries[1]["text"]) == "first"
    assert ticket_view.latest_tab_line([_line("answered", "4")]) is None


def test_the_operators_words_a_tab_quoted_are_no_next_step_of_the_tab():
    entries = [_line("opened", "1", "ses_a", "the request"), _line("operator", "1", "ses_a", "the operator's own words")]
    assert ticket_view.latest_tab_line(entries) is entries[0]
    assert ticket_view.latest_tab_line(entries[1:]) is None


def test_the_first_line_of_a_text_ignores_blank_lines_before_it_and_is_empty_for_no_text():
    assert ticket_view.first_line("\n\n  go on  \nmore") == "go on"
    assert ticket_view.first_line("") == "" and ticket_view.first_line(None) == ""


def test_a_ticket_comes_from_the_operator_from_another_tab_or_from_the_holder_itself():
    assert ticket_view.source_of("operator", "ses_a", "ses_a") == "operator"
    assert ticket_view.source_of("operator", "ses_a", "ses_b") == "operator"
    assert ticket_view.source_of("self", "ses_a", "ses_b") == "tab"
    assert ticket_view.source_of("self", "ses_a", "ses_a") == "self"
    assert ticket_view.source_of("self", "company:ses_x", "ses_a") == "tab"


def test_a_tab_has_written_since_a_time_only_by_a_line_of_its_own_at_or_after_it():
    entries = [_line("added", "2026-11-21T01:00:00.000+00:00", "ses_a"), _line("added", "2026-11-21T03:00:00.000+00:00", "ses_b"),
               _line("delivered", "2026-11-21T04:00:00.000+00:00")]
    assert ticket_view.written_since(entries, "ses_a", "2026-11-21T01:00:00.000Z") is True
    assert ticket_view.written_since(entries, "ses_a", "2026-11-21T01:00:00.001Z") is False
    assert ticket_view.written_since(entries, "ses_a", "2026-11-21T10:00:00+09:00") is True       # 01:00 UTC
    assert ticket_view.written_since(entries, "ses_c", "2026-11-21T00:00:00Z") is False
    assert ticket_view.written_since(entries, "ses_a", "yesterday") is None


def test_times_are_compared_as_times_and_not_as_text():
    entries = [_line("added", "2026-11-21T00:30:00.000+00:00", "ses_a")]
    assert ticket_view.written_since(entries, "ses_a", "2026-11-21T09:00:00+09:00") is True        # 00:00 UTC, before 00:30
    assert ticket_view.written_since(entries, "ses_a", "2026-11-21T09:45:00+09:00") is False       # 00:45 UTC, after 00:30
