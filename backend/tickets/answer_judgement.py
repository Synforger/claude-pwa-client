"""What to do with one answer in the queue, and with the holder of a ticket that may be gone. Pure: no file, no tab, no clock
(= the caller reads the facts and passes them). `next_step` is the table of delivering, `after_failure` says what a refused
delivery leaves of the answer, `retry_after_sec` the wait before the next try, and `return_step` the table of giving a
ticket back to the tab that asked first. Called by `answer_delivery.py` and `ticket_return.py`.
"""
from __future__ import annotations

from typing import NamedTuple

#: The wait before an answer that was refused before anything was typed is tried again: the first one, and how it grows
#: (= doubles) up to a limit, so that a tab that cannot be started is not woken every few seconds
RETRY_FIRST_SEC = 5.0
RETRY_FACTOR = 2.0
RETRY_MAX_SEC = 300.0

# What `next_step` answers
DELIVER = "deliver"
#: The tab is working (or was asked to close): type nothing, keep the answer for the next look
WAIT_BUSY = "wait_busy"
#: Nothing is typed and the answer stays: nobody holds the ticket now (or the holder is on another machine)
WAIT_NO_HOLDER = "wait_no_holder"
#: The holder is not a tab of this machine any more: give the ticket back first (`return_step`), then ask again
RETURN_HOLDER = "return_holder"
#: The message cannot start the holder's claude; try again after the wait
RETRY_UNREACHABLE = "retry_unreachable"
#: A ticket that closed has no holder left to tell: the answer is let go
NO_RECEIVER = "no_receiver"
#: The index has no row of the ticket: the answer is let go
DROP_NO_TICKET = "drop_no_ticket"

# What `after_failure` answers
RETRY = "retry"
UNCONFIRMED = "unconfirmed"
REFUSED = "refused"

# What `return_step` answers
STAY = "stay"
RETURN_TO_OPENER = "return_to_opener"
CLEAR_HOLDER = "clear_holder"

#: Codes of a delivery that may have arrived: it is not typed again (= two answers are worse than one the operator checks)
_AFTER_TYPING = ("agent_message_unconfirmed", "agent_message_not_taken")
#: The tab never read the boundary of the ticket's place: it is not given the answer
_NOT_ALLOWED = ("ticket_outside_place",)


class AnswerFacts(NamedTuple):
    """What is known when one answer is looked at."""

    has_row: bool         # the index has a row of the ticket
    closed: bool          # the ticket is closed
    holder: str           # the index's holder (= "" when no tab holds it)
    holder_is_remote: bool  # the holder is a tab of another machine (`<machine>:<id>`)
    holder_here: bool     # the holder is a tab of this machine now
    reachable: bool       # a message reaches the holder (= its claude runs, or the message can start it)
    busy: bool            # the holder's claude is working
    close_asked: bool     # the holder's conversation was asked to close (the rollover)


class HolderFacts(NamedTuple):
    """What is known when the holder of an open ticket is looked at."""

    holder: str
    holder_is_remote: bool
    holder_here: bool
    opener_here: bool


def next_step(facts: AnswerFacts) -> str:
    """The step for one answer, the first row of the table that fits."""
    if not facts.has_row:
        return DROP_NO_TICKET
    if not facts.holder or facts.holder_is_remote:
        return WAIT_NO_HOLDER
    if not facts.holder_here:
        return NO_RECEIVER if facts.closed else RETURN_HOLDER
    if facts.busy or facts.close_asked:
        return WAIT_BUSY
    if not facts.reachable:
        return RETRY_UNREACHABLE
    return DELIVER


def after_failure(code: str) -> str:
    """What is left of the answer after a delivery failed with `code`: `RETRY` (nothing was typed, so it is tried again
    after the wait), `UNCONFIRMED` (it may have arrived, so it is not typed again) or `REFUSED` (the tab may not have it).
    A code nobody foresaw is `RETRY`: the answer is the operator's words, and they are kept until they arrive."""
    if code in _AFTER_TYPING:
        return UNCONFIRMED
    if code in _NOT_ALLOWED:
        return REFUSED
    return RETRY


def retry_after_sec(previous_sec: float | None) -> float:
    """The wait before the next try of an answer, given the wait before this one (None = this is the first try)."""
    if previous_sec is None:
        return RETRY_FIRST_SEC
    return min(previous_sec * RETRY_FACTOR, RETRY_MAX_SEC)


def return_step(facts: HolderFacts) -> str:
    """What to do with the holder of an open ticket: leave it, give the ticket back to the tab that asked first, or hold
    it with no tab (= neither is here). A holder on another machine is left as it is: only the tabs of this machine are
    judged here."""
    if not facts.holder or facts.holder_is_remote or facts.holder_here:
        return STAY
    return RETURN_TO_OPENER if facts.opener_here else CLEAR_HOLDER
