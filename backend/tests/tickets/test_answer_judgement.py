"""The tables of delivering an answer (one test for each row), of what a refused delivery leaves of the answer, of the wait
before a new try, and of giving a ticket back to the tab that asked first."""
from __future__ import annotations

import pytest

from backend.tickets import answer_judgement as judgement
from backend.tickets.answer_judgement import AnswerFacts, HolderFacts


def _facts(**changes) -> AnswerFacts:
    """An idle tab of this machine that holds an open ticket and can be reached."""
    base = dict(has_row=True, closed=False, holder="ses_b", holder_is_remote=False, holder_here=True, reachable=True,
                busy=False, close_asked=False)
    return AnswerFacts(**{**base, **changes})


def test_an_idle_tab_that_can_be_reached_is_typed_to():
    assert judgement.next_step(_facts()) == judgement.DELIVER


def test_a_working_tab_is_not_typed_to_and_the_answer_waits():
    assert judgement.next_step(_facts(busy=True)) == judgement.WAIT_BUSY


def test_a_tab_asked_to_close_is_not_typed_to_and_the_answer_waits_for_the_next_conversation():
    assert judgement.next_step(_facts(close_asked=True)) == judgement.WAIT_BUSY


def test_a_tab_the_stop_button_stopped_counts_as_idle():
    # `is_busy` is false once the operator stopped the turn, so the answer is typed (= the facts carry no separate flag)
    assert judgement.next_step(_facts(busy=False)) == judgement.DELIVER


def test_a_tab_that_cannot_be_started_is_tried_again_after_a_wait():
    assert judgement.next_step(_facts(reachable=False)) == judgement.RETRY_UNREACHABLE


def test_a_holder_that_is_gone_from_an_open_ticket_means_giving_the_ticket_back_first():
    assert judgement.next_step(_facts(holder_here=False, reachable=False)) == judgement.RETURN_HOLDER


def test_a_holder_that_is_gone_from_a_closed_ticket_leaves_nobody_to_tell():
    assert judgement.next_step(_facts(holder_here=False, closed=True)) == judgement.NO_RECEIVER


def test_no_holder_means_waiting_for_the_operator_to_choose_one():
    assert judgement.next_step(_facts(holder="", holder_here=False)) == judgement.WAIT_NO_HOLDER


def test_a_holder_on_another_machine_is_not_typed_to_from_here():
    assert judgement.next_step(_facts(holder="office:ses_x", holder_is_remote=True, holder_here=False)) == judgement.WAIT_NO_HOLDER


def test_a_closed_ticket_is_typed_to_all_the_same():
    assert judgement.next_step(_facts(closed=True)) == judgement.DELIVER


def test_a_ticket_with_no_row_in_the_index_is_let_go():
    assert judgement.next_step(_facts(has_row=False)) == judgement.DROP_NO_TICKET


@pytest.mark.parametrize("code", ["agent_message_unconfirmed", "agent_message_not_taken"])
def test_a_delivery_that_may_have_arrived_is_not_typed_again(code):
    assert judgement.after_failure(code) == judgement.UNCONFIRMED


@pytest.mark.parametrize("code", ["agent_message_receiver_not_running", "agent_message_receiver_not_ready",
                                  "agent_message_not_sent", "ticket_check_failed", "ticket_place_unknown", "something_new"])
def test_a_delivery_refused_before_anything_was_typed_is_tried_again(code):
    assert judgement.after_failure(code) == judgement.RETRY


def test_a_tab_that_has_not_read_the_boundary_is_not_given_the_answer():
    assert judgement.after_failure("ticket_outside_place") == judgement.REFUSED


def test_the_wait_starts_at_5_seconds_and_doubles_up_to_5_minutes():
    waits, wait = [], None
    for _ in range(8):
        wait = judgement.retry_after_sec(wait)
        waits.append(wait)
    assert waits == [5, 10, 20, 40, 80, 160, 300, 300]


def test_a_holder_that_is_here_stays_the_holder():
    assert judgement.return_step(HolderFacts("ses_b", False, True, True)) == judgement.STAY


def test_a_holder_that_is_gone_gives_the_ticket_back_to_the_tab_that_asked_first():
    assert judgement.return_step(HolderFacts("ses_b", False, False, True)) == judgement.RETURN_TO_OPENER


def test_when_the_tab_that_asked_first_is_gone_too_nobody_holds_the_ticket():
    assert judgement.return_step(HolderFacts("ses_b", False, False, False)) == judgement.CLEAR_HOLDER


def test_a_ticket_nobody_holds_stays_so():
    assert judgement.return_step(HolderFacts("", False, False, True)) == judgement.STAY


def test_a_holder_on_another_machine_is_never_given_back_from_here():
    assert judgement.return_step(HolderFacts("office:ses_x", True, False, True)) == judgement.STAY
