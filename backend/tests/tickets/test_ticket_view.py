"""What the screen is given of a ticket: the answers still on their way, how the last delivery ended, why a ticket wants a look,
the words of its notification and the other machine's waiting count."""
from __future__ import annotations

import pytest

from backend.tickets import ticket_view


def _line(kind: str, at: str, **extra) -> dict:
    return {"kind": kind, "at": at, **extra}


def test_an_answer_without_a_delivered_line_is_on_its_way():
    entries = [_line("answered", "2", asked_at="1"), _line("answered", "4", asked_at="3"), _line("delivered", "5", asked_at="1")]
    assert ticket_view.answer_pending(entries) == ["3"]


def test_no_answer_is_pending_when_every_one_was_delivered_or_none_was_given():
    assert ticket_view.answer_pending([_line("asked", "1")]) == []
    assert ticket_view.answer_pending([_line("answered", "2", asked_at="1"), _line("delivered", "3", asked_at="1")]) == []


def test_the_last_delivery_says_how_it_ended_and_whether_a_line_came_after():
    entries = [_line("delivered", "1", result="typed", asked_at="a"), _line("delivered", "3", result="refused", asked_at="b")]
    assert ticket_view.last_delivery(entries) == {"result": "refused", "followed": False}
    assert ticket_view.last_delivery([*entries, _line("seen", "4")]) == {"result": "refused", "followed": True}
    assert ticket_view.last_delivery([_line("opened", "0")]) is None


def test_last_at_is_the_time_of_the_last_line_or_empty():
    assert ticket_view.last_at([_line("opened", "1"), _line("added", "2")]) == "2"
    assert ticket_view.last_at([]) == ""


@pytest.mark.parametrize("status, holder, delivery, expected", [
    ("waiting-operator", "ses_a", None, "waiting"),
    ("waiting-operator", "", None, "waiting"),
    ("open", "ses_a", {"result": "refused", "followed": False}, "delivery"),
    ("closed", "ses_a", {"result": "unconfirmed", "followed": False}, "delivery"),
    ("open", "ses_a", {"result": "refused", "followed": True}, None),
    ("open", "ses_a", {"result": "typed", "followed": False}, None),
    ("open", "", None, "no_holder"),
    ("closed", "", None, None),
    ("open", "ses_a", None, None),
])
def test_a_ticket_wants_a_look_for_the_first_reason_that_fits(status, holder, delivery, expected):
    assert ticket_view.attention(status, holder, delivery) == expected


def test_a_ticket_kept_inside_a_boundary_is_named_by_its_id_only():
    assert ticket_view.notice_of("home-261119-01", None, "waiting", wants="decide") == (
        "📌 Ticket home-261119-01", "Waiting for your decision")
    assert ticket_view.notice_of("home-261119-01", "Fix the title", "waiting", wants="mac") == (
        "📌 Fix the title", "Needs you at the Mac")


def test_the_words_of_a_notification_follow_the_reason():
    assert ticket_view.notice_of("t", "T", "delivery", result="unconfirmed")[1] == "Check that your answer arrived"
    assert ticket_view.notice_of("t", "T", "delivery", result="refused")[1] == "Your answer was not delivered"
    assert ticket_view.notice_of("t", "T", "no_holder")[1] == "No tab holds this ticket"


def test_the_waiting_count_counts_the_tickets_that_wait_for_the_operator():
    listing = {"ok": True, "tickets": [{"status": "waiting-operator"}, {"status": "open"}, {"status": "waiting-operator"}]}
    assert ticket_view.waiting_count(listing) == 2
    assert ticket_view.waiting_count({"tickets": []}) == 0


@pytest.mark.parametrize("listing", [None, {}, {"tickets": "x"}, {"detail": "no"}])
def test_a_machine_that_gave_no_list_is_unreadable_and_not_zero(listing):
    assert ticket_view.waiting_count(listing) is None
