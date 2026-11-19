"""The operator's answer to a ticket that waits for it: what is refused, what is written (the `answered` line and the row,
together), the queue it goes into and the door that takes it."""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.routes import tickets as tickets_routes
from backend.tests.async_run import run
from backend.tests.tickets.samples import answered_ticket, asked_at_of, delivery_env, queued, waiting_ticket  # noqa: F401
from backend.tests.tickets.samples import ticket_env  # noqa: F401
from backend.tickets import ticket_answer, ticket_file, ticket_index, ticket_service
from backend.tickets.answer_queue import AnswerKey


def _code(coroutine) -> str:
    with pytest.raises(HTTPException) as refused:
        run(coroutine)
    return refused.value.detail["code"]


def test_an_answer_in_words_is_written_into_the_ticket_and_the_row_opens_again(delivery_env):
    ticket = waiting_ticket()
    asked_at = asked_at_of(delivery_env.tickets, ticket)
    assert run(ticket_answer.answer(ticket, asked_at, "Take B", False)) == {"ok": True, "id": ticket, "queued": True}
    last = ticket_file.read(delivery_env.tickets, ticket)[-1]
    assert (last["kind"], last["asked_at"], last["text"], last["recommended"]) == ("answered", asked_at, "Take B", False)
    assert (last["tab"], last["tab_title"], last["tier"]) == ("", "", "")
    row = ticket_index.get(ticket)
    assert (row.status, row.wants, row.holder) == ("open", None, "ses_a")


def test_an_answer_by_the_recommendation_carries_the_words_of_the_recommendation(delivery_env):
    ticket = waiting_ticket(recommend="Take A")
    run(ticket_answer.answer(ticket, asked_at_of(delivery_env.tickets, ticket), "", True))
    last = ticket_file.read(delivery_env.tickets, ticket)[-1]
    assert (last["text"], last["recommended"]) == ("Take A", True)


def test_the_answer_is_queued_by_ticket_and_asked_line_and_delivery_starts(delivery_env):
    key = answered_ticket(delivery_env)
    assert queued() == [key] and delivery_env.started == [key]


def test_a_second_answer_to_the_same_line_is_refused_because_the_ticket_no_longer_waits(delivery_env):
    ticket = waiting_ticket()
    asked_at = asked_at_of(delivery_env.tickets, ticket)
    run(ticket_answer.answer(ticket, asked_at, "Take B", False))
    assert _code(ticket_answer.answer(ticket, asked_at, "Take A", False)) == "ticket_not_waiting"
    assert queued() == [AnswerKey(ticket, asked_at)]


def test_a_ticket_that_is_not_there_is_unknown(delivery_env):
    assert _code(ticket_answer.answer("home-261119-77", "x", "Take B", False)) == "ticket_unknown"


def test_a_ticket_that_does_not_wait_for_the_operator_is_refused(delivery_env):
    ticket = run(ticket_service.open_ticket("ses_a", "Title", "Request", operator_said=False))["id"]
    assert _code(ticket_answer.answer(ticket, "x", "Take B", False)) == "ticket_not_waiting"


def test_an_answer_to_a_line_that_is_no_longer_the_last_asked_is_refused(delivery_env, monkeypatch):
    times = iter(f"2026-11-19T00:00:{second:02d}.000+00:00" for second in range(60))
    monkeypatch.setattr(ticket_service, "now", lambda: next(times))          # two asks never share a millisecond
    ticket = waiting_ticket()
    old = asked_at_of(delivery_env.tickets, ticket)
    run(ticket_service.ask("ses_a", ticket, "decide", "Or C?", None))
    assert _code(ticket_answer.answer(ticket, old, "Take B", False)) == "ticket_ask_changed"
    assert ticket_index.get(ticket).status == "waiting-operator" and queued() == []


def test_a_ticket_no_tab_holds_is_refused(delivery_env):
    ticket = waiting_ticket()
    ticket_index.put(ticket, ticket_index.get(ticket)._replace(holder=""))
    assert _code(ticket_answer.answer(ticket, asked_at_of(delivery_env.tickets, ticket), "Take B", False)) == "ticket_no_holder"
    assert queued() == []


def test_the_recommendation_is_refused_when_the_question_has_none(delivery_env):
    ticket = waiting_ticket(recommend=None)
    assert _code(ticket_answer.answer(ticket, asked_at_of(delivery_env.tickets, ticket), "", True)) == "ticket_no_recommend"


def test_the_answer_is_not_judged_by_the_guard(delivery_env):
    ticket = waiting_ticket()
    delivery_env.guard.use("write", write={"status": 1})        # from here the guard refuses every line a tab adds
    run(ticket_answer.answer(ticket, asked_at_of(delivery_env.tickets, ticket), "Take B", False))
    assert delivery_env.guard.calls("write") == [] and queued() != []


@pytest.fixture
def door(delivery_env):
    app = FastAPI()
    app.include_router(tickets_routes.router)
    return TestClient(app)


def test_the_door_takes_the_asked_line_and_the_words(delivery_env, door):
    ticket = waiting_ticket()
    asked_at = asked_at_of(delivery_env.tickets, ticket)
    answer = door.post(f"/tickets/{ticket}/answer", json={"asked_at": asked_at, "text": "Take B"})
    assert (answer.status_code, answer.json()) == (200, {"ok": True, "id": ticket, "queued": True})


def test_the_door_takes_recommend_true_and_does_not_read_the_words_then(delivery_env, door):
    ticket = waiting_ticket(recommend="Take A")
    answer = door.post(f"/tickets/{ticket}/answer", json={"asked_at": asked_at_of(delivery_env.tickets, ticket),
                                                          "text": "ignored", "recommend": True})
    assert answer.status_code == 200
    assert ticket_file.read(delivery_env.tickets, ticket)[-1]["text"] == "Take A"


@pytest.mark.parametrize("body, status, code", [
    ({"text": "Take B"}, 400, "ticket_bad_answer"),
    ({"asked_at": "  ", "text": "Take B"}, 400, "ticket_bad_answer"),
    ({"asked_at": "x", "text": 5}, 400, "ticket_bad_answer"),
    ({"asked_at": "x", "text": "  "}, 400, "ticket_empty"),
    ({"asked_at": "x"}, 400, "ticket_empty"),
])
def test_the_door_refuses_a_form_it_cannot_read_and_an_empty_text(delivery_env, door, body, status, code):
    ticket = waiting_ticket()
    answer = door.post(f"/tickets/{ticket}/answer", json=body)
    assert (answer.status_code, answer.json()["detail"]["code"]) == (status, code)
    assert queued() == []


def test_the_door_answers_404_for_an_id_that_is_not_a_ticket_id(delivery_env, door):
    answer = door.post("/tickets/not-an-id/answer", json={"asked_at": "x", "text": "Take B"})
    assert (answer.status_code, answer.json()["detail"]["code"]) == (404, "ticket_unknown")
