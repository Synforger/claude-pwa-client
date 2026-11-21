"""The picture of the tickets the screen is given on the `tickets` channel: each ticket carries the same fields as the list."""
from __future__ import annotations

from backend.tests.async_run import run
from backend.tests.tickets.samples import ticket_env  # noqa: F401
from backend.tickets import ticket_feed, ticket_service


def test_a_ticket_of_the_stream_has_the_origin_the_due_day_and_the_marks_of_the_list_and_may_wait(ticket_env):
    ticket = run(ticket_service.open_ticket("ses_a", "Late", "Request", operator_said=True, due="2000-01-01"))["id"]
    run(ticket_service.add("ses_a", ticket, "waits for the review", waiting=True))
    picture = run(ticket_feed.snapshot())
    [streamed] = picture["tickets"]
    assert (streamed["status"], streamed["origin"], streamed["due"], streamed["marks"]) == ("waiting", "operator", "2000-01-01", ["overdue"])
    assert picture["tickets"] == run(ticket_service.list_tickets())["tickets"] and picture["peers"] == {}
