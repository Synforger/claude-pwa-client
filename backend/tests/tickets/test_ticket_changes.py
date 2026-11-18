"""Adding to a ticket, asking the operator through it, closing it, reading it, listing them, and two lines added at once."""
from __future__ import annotations

import threading

import pytest
from fastapi import HTTPException

from backend.tests.async_run import run
from backend.tests.tickets.samples import ticket_env  # noqa: F401
from backend.tickets import ticket_entry, ticket_file, ticket_index, ticket_places, ticket_service
from backend.tickets.ticket_entry import Writer


def _ticket() -> str:
    return run(ticket_service.open_ticket("ses_a", "Title", "Request", operator_said=False))["id"]


def _code(coroutine) -> str:
    with pytest.raises(HTTPException) as refused:
        run(coroutine)
    return refused.value.detail["code"]


def test_adding_puts_a_line_in_and_leaves_the_holder_where_it_is(ticket_env):
    ticket = _ticket()
    answer = run(ticket_service.add("ses_b", ticket, "I did it"))
    assert answer == {"ok": True, "id": ticket, "status": "open"}
    last = ticket_file.read(ticket_env.tickets, ticket)[-1]
    assert (last["kind"], last["tab"], last["tab_title"], last["text"]) == ("added", "ses_b", "notes", "I did it")
    assert ticket_index.get(ticket).holder == "ses_a"


def test_asking_puts_the_ticket_in_front_of_the_operator_with_the_recommendation(ticket_env):
    ticket = _ticket()
    assert run(ticket_service.ask("ses_a", ticket, "decide", "A or B?", "A")) == {"ok": True, "id": ticket,
                                                                              "status": "waiting-operator"}
    last = ticket_file.read(ticket_env.tickets, ticket)[-1]
    assert (last["kind"], last["ask_kind"], last["text"], last["recommend"]) == ("asked", "decide", "A or B?", "A")
    row = ticket_index.get(ticket)
    assert (row.status, row.wants) == ("waiting-operator", "decide")


def test_an_ask_without_a_recommendation_has_no_recommend_field(ticket_env):
    ticket = _ticket()
    run(ticket_service.ask("ses_a", ticket, "report", "Done.", None))
    assert "recommend" not in ticket_file.read(ticket_env.tickets, ticket)[-1]


def test_closing_ends_the_ticket_and_it_stays(ticket_env):
    ticket = _ticket()
    assert run(ticket_service.close("ses_a", ticket, "All done"))["status"] == "closed"
    assert ticket_file.read(ticket_env.tickets, ticket)[-1]["kind"] == "closed"
    assert ticket_index.get(ticket).status == "closed"


def test_a_ticket_may_be_closed_without_a_last_word(ticket_env):
    ticket = _ticket()
    run(ticket_service.close("ses_a", ticket, ""))
    assert ticket_file.read(ticket_env.tickets, ticket)[-1]["text"] == ""


@pytest.mark.parametrize("change", [
    lambda t: ticket_service.add("ses_b", t, "more"),
    lambda t: ticket_service.ask("ses_b", t, "mac", "more", None),
    lambda t: ticket_service.close("ses_b", t, ""),
])
def test_a_closed_ticket_takes_no_more_lines(ticket_env, change):
    ticket = _ticket()
    run(ticket_service.close("ses_a", ticket, ""))
    before = (ticket_env.tickets / f"{ticket}.jsonl").read_text(encoding="utf-8")
    assert _code(change(ticket)) == "ticket_closed"
    assert (ticket_env.tickets / f"{ticket}.jsonl").read_text(encoding="utf-8") == before


def test_a_ticket_that_closes_while_a_change_is_being_made_refuses_the_change(ticket_env):
    ticket = _ticket()
    ticket_index.put(ticket, ticket_index.get(ticket)._replace(status="closed"))
    entry = ticket_entry.make_entry(ticket_entry.ADDED, Writer("ses_b", "notes", ""), "late", at="t")
    with pytest.raises(HTTPException) as refused:
        ticket_service.write_entry(ticket, ticket_env.tickets, entry)
    assert refused.value.detail["code"] == "ticket_closed"


def test_an_unknown_ticket_is_unknown_to_every_change_and_to_reading(ticket_env):
    for change in (ticket_service.add("ses_b", "home-261119-09", "x"), ticket_service.close("ses_b", "home-261119-09", ""),
                   ticket_service.ask("ses_b", "home-261119-09", "mac", "x", None),
                   ticket_service.show("ses_b", "home-261119-09")):
        assert _code(change) == "ticket_unknown"


def test_showing_gives_the_state_the_holder_and_every_line_by_time(ticket_env):
    ticket = _ticket()
    run(ticket_service.add("ses_b", ticket, "step 1"))
    run(ticket_service.ask("ses_a", ticket, "mac", "plug it in", None))
    shown = run(ticket_service.show("ses_c", ticket))
    assert (shown["status"], shown["wants"], shown["holder"], shown["opener"], shown["place_outside"]) == (
        "waiting-operator", "mac", "ses_a", "ses_a", True)
    assert [entry["kind"] for entry in shown["entries"]] == ["opened", "added", "asked"]


def test_listing_gives_each_ticket_with_the_title_read_from_its_place_newest_first(ticket_env):
    first = _ticket()
    second = run(ticket_service.open_ticket("ses_b", "Second title", "x", operator_said=False))["id"]
    listed = run(ticket_service.list_tickets())["tickets"]
    assert [(row["id"], row["title"], row["opener"], row["status"]) for row in listed] == [
        (second, "Second title", "ses_b", "open"), (first, "Title", "ses_a", "open")]


def test_a_ticket_whose_place_is_not_known_is_listed_without_a_title(ticket_env):
    ticket_index.put("home-261119-07", ticket_index.IndexRow("0123456789abcdef", "ses_a", "ses_a", "open", None))
    listed = run(ticket_service.list_tickets())["tickets"]
    assert [(row["id"], row["title"]) for row in listed] == [("home-261119-07", None)]


def test_lines_added_at_the_same_time_do_not_wipe_each_other_out(ticket_env):
    ticket = _ticket()
    writer = Writer("ses_b", "notes", "")

    def add_many(worker: int) -> None:
        for number in range(25):
            entry = ticket_entry.make_entry(ticket_entry.ADDED, writer, f"worker {worker} line {number}", at=f"t{worker}-{number}")
            ticket_service.write_entry(ticket, ticket_env.tickets, entry)

    threads = [threading.Thread(target=add_many, args=(worker,)) for worker in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    texts = [entry["text"] for entry in ticket_file.read(ticket_env.tickets, ticket) if entry["kind"] == "added"]
    assert sorted(texts) == sorted(f"worker {w} line {n}" for w in range(8) for n in range(25))


def test_tickets_opened_at_the_same_time_get_different_ids(ticket_env):
    ids: list[str] = []

    def open_one() -> None:
        ids.append(_ticket())

    threads = [threading.Thread(target=open_one) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(set(ids)) == 10 == len(ticket_index.rows())
