"""The state of a ticket after each thing that can happen to it, one test for each row of the table of states (`open`, `waiting`,
`waiting-operator`, `closed`), and that the next state is worked out from the row under the ticket's lock."""
from __future__ import annotations

from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException

from backend.tests.async_run import run
from backend.tests.tickets.samples import asked_at_of, delivery_env, ticket_env  # noqa: F401
from backend.tickets import ticket_answer, ticket_file, ticket_index, ticket_pass, ticket_service, ticket_state


@pytest.fixture
def delivered(monkeypatch):
    """Every tab is reachable and takes what is typed."""
    async def deliver(tab_id, text):
        return {"ok": True}

    monkeypatch.setattr(ticket_pass, "deliver_or_keep", deliver)
    monkeypatch.setattr(ticket_pass, "tab_reachable", AsyncMock(return_value=True))


def _ticket(status: str = "open") -> str:
    """A ticket opened by `ses_a`, in `status` (= `waiting` is reached through `add --waiting`, as a tab reaches it)."""
    ticket = run(ticket_service.open_ticket("ses_a", "Title", "Request", operator_said=False))["id"]
    if status == "waiting":
        run(ticket_service.add("ses_a", ticket, "waits for the build", waiting=True))
    return ticket


def _status(ticket: str) -> str:
    return ticket_index.get(ticket).status


def _code(coroutine) -> str:
    with pytest.raises(HTTPException) as refused:
        run(coroutine)
    return refused.value.detail["code"]


# --- add ---


@pytest.mark.parametrize("before", ["open", "waiting"])
def test_a_plain_add_leaves_an_open_ticket_open_and_puts_a_waiting_one_back_to_open(ticket_env, before):
    ticket = _ticket(before)
    assert run(ticket_service.add("ses_a", ticket, "went on")) == {"ok": True, "id": ticket, "status": "open"}
    assert _status(ticket) == "open"


@pytest.mark.parametrize("before", ["open", "waiting"])
def test_an_add_with_the_waiting_mark_sets_the_ticket_aside_and_the_line_says_so(ticket_env, before):
    ticket = _ticket(before)
    assert run(ticket_service.add("ses_a", ticket, "waits for the review", waiting=True))["status"] == "waiting"
    assert _status(ticket) == "waiting" and ticket_file.read(ticket_env.tickets, ticket)[-1]["waiting"] is True


def test_an_add_with_a_due_day_sets_it_and_keeps_the_state(ticket_env):
    ticket = _ticket("waiting")
    run(ticket_service.add("ses_a", ticket, "waits", waiting=True, due="2026-12-24"))
    row = ticket_index.get(ticket)
    assert (row.status, row.due) == ("waiting", "2026-12-24")
    assert ticket_file.read(ticket_env.tickets, ticket)[-1]["due"] == "2026-12-24"


def test_an_add_without_a_due_day_keeps_the_one_the_ticket_has(ticket_env):
    ticket = run(ticket_service.open_ticket("ses_a", "T", "R", operator_said=False, due="2026-12-01"))["id"]
    run(ticket_service.add("ses_a", ticket, "went on"))
    assert ticket_index.get(ticket).due == "2026-12-01"


# --- ask and the operator's answer ---


@pytest.mark.parametrize("before", ["open", "waiting"])
def test_an_ask_puts_an_open_or_waiting_ticket_in_front_of_the_operator(ticket_env, before):
    ticket = _ticket(before)
    assert run(ticket_service.ask("ses_a", ticket, "decide", "A or B?", None))["status"] == "waiting-operator"
    assert ticket_index.get(ticket).wants == "decide"


def test_the_operators_answer_opens_the_ticket_again(delivery_env):
    ticket = run(ticket_service.open_ticket("ses_a", "T", "R", operator_said=False))["id"]
    run(ticket_service.ask("ses_a", ticket, "decide", "A or B?", None))
    run(ticket_answer.answer(ticket, asked_at_of(delivery_env.tickets, ticket), "B", False))
    row = ticket_index.get(ticket)
    assert (row.status, row.wants) == ("open", None)


@pytest.mark.parametrize("waiting", [False, True])
def test_an_add_to_a_ticket_that_waits_for_the_operator_leaves_it_waiting_whatever_the_mark(ticket_env, waiting):
    ticket = _ticket()
    run(ticket_service.ask("ses_a", ticket, "decide", "A or B?", None))
    assert run(ticket_service.add("ses_a", ticket, "more", waiting=waiting))["status"] == "waiting-operator"
    assert ticket_index.get(ticket).wants == "decide"


def test_an_add_with_only_a_due_day_to_a_ticket_that_waits_for_the_operator_changes_only_the_due_day(ticket_env):
    ticket = _ticket()
    run(ticket_service.ask("ses_a", ticket, "decide", "A or B?", None))
    run(ticket_service.add("ses_a", ticket, "the decision is due soon", due="2026-12-02"))
    row = ticket_index.get(ticket)
    assert (row.status, row.due) == ("waiting-operator", "2026-12-02")


def test_asking_again_keeps_the_ticket_waiting_and_changes_what_it_wants(ticket_env):
    ticket = _ticket()
    run(ticket_service.ask("ses_a", ticket, "decide", "A or B?", None))
    run(ticket_service.ask("ses_a", ticket, "mac", "Please plug it in", None))
    row = ticket_index.get(ticket)
    assert (row.status, row.wants) == ("waiting-operator", "mac")


def test_an_ask_that_lands_between_the_reading_and_the_writing_of_an_add_is_not_undone(ticket_env, monkeypatch):
    ticket = _ticket()
    prepare = ticket_service._prepare

    async def prepare_then_ask(sender, ticket_id, judged):
        found = await prepare(sender, ticket_id, judged)
        ticket_index.put(ticket_id, ticket_index.get(ticket_id)._replace(status="waiting-operator", wants="decide"))
        return found

    monkeypatch.setattr(ticket_service, "_prepare", prepare_then_ask)
    assert run(ticket_service.add("ses_a", ticket, "went on"))["status"] == "waiting-operator"
    assert _status(ticket) == "waiting-operator"


# --- pass ---


@pytest.mark.parametrize("before", ["open", "waiting"])
def test_a_ticket_that_is_passed_is_open_with_the_tab_it_went_to(ticket_env, delivered, before):
    ticket = _ticket(before)
    run(ticket_pass.pass_ticket("ses_a", ticket, "ses_b"))
    row = ticket_index.get(ticket)
    assert (row.status, row.holder) == ("open", "ses_b")


def test_a_ticket_that_waits_for_the_operator_is_not_passed_and_stays_as_it_was(ticket_env, delivered):
    ticket = _ticket()
    run(ticket_service.ask("ses_a", ticket, "decide", "A or B?", None))
    assert _code(ticket_pass.pass_ticket("ses_a", ticket, "ses_b")) == "ticket_waiting_operator"
    assert (_status(ticket), ticket_index.get(ticket).holder) == ("waiting-operator", "ses_a")


def test_the_operator_giving_a_waiting_ticket_a_holder_leaves_it_waiting_for_them(ticket_env, delivered):
    ticket = _ticket()
    run(ticket_service.ask("ses_a", ticket, "decide", "A or B?", None))
    ticket_index.put(ticket, ticket_index.get(ticket)._replace(holder=""))
    run(ticket_pass.hand_over(ticket, ticket_pass.OPERATOR_PARTY, ticket_pass.Party(None, "ses_b"), by_operator=True))
    row = ticket_index.get(ticket)
    assert (row.status, row.holder) == ("waiting-operator", "ses_b")


# --- close ---


@pytest.mark.parametrize("before", ["open", "waiting", "waiting-operator"])
def test_a_ticket_that_is_not_closed_closes_from_any_state(ticket_env, before):
    ticket = _ticket("waiting" if before == "waiting" else "open")
    if before == "waiting-operator":
        run(ticket_service.ask("ses_a", ticket, "decide", "A or B?", None))
    assert run(ticket_service.close("ses_a", ticket, "done"))["status"] == "closed"
    assert ticket_index.get(ticket).wants is None


# --- the form of the changes ---


def test_a_change_may_be_a_function_of_the_row_and_gets_the_row_as_it_is_under_the_lock(ticket_env):
    ticket = _ticket()
    seen = []

    def change(row):
        seen.append(row.status)
        return {"due": "2027-01-01"}

    entry = {"kind": "added", "at": ticket_service.now(), "tab": "ses_a", "tab_title": "", "tier": "", "text": "x"}
    ticket_service.write_entry(ticket, ticket_env.tickets, entry, change)
    assert seen == ["open"] and ticket_index.get(ticket).due == "2027-01-01"


@pytest.mark.parametrize("text, day", [("2026-12-01", "2026-12-01"), (" 2026-12-01\n", "2026-12-01"), ("2026-02-30", None),
                                       ("2026-W48-1", None), ("20261201", None), ("12/01", None), ("", None)])
def test_a_due_day_is_a_day_that_exists_in_the_form_year_month_day(text, day):
    assert ticket_state.parse_due(text) == day
