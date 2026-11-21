"""The tickets a tab holds (`tabs ticket mine`): whose tickets are listed, what the tab may read of each, the marks, whether the
tab itself wrote since a time, whether it may write there, the other machine's tickets and a machine that does not answer."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.tests.async_run import run
from backend.tests.tickets.samples import outside_ticket, relay_env  # noqa: F401
from backend.tests.tickets.samples import ticket_env  # noqa: F401
from backend.tickets import ticket_entry, ticket_file, ticket_held, ticket_index, ticket_service

BEFORE = "2000-01-01T00:00:00.000Z"
PEER_LIST = "/agent-messages/tickets"


def _held(tab: str = "ses_a", since: str | None = None) -> dict:
    return run(ticket_held.held_by(tab, since))


def _ids(answer: dict) -> list[str]:
    return [ticket["id"] for ticket in answer["tickets"]]


def _hold(ticket: str, holder: str, **row) -> None:
    ticket_index.put(ticket, ticket_index.get(ticket)._replace(holder=holder, **row))


def _line(folder, ticket: str, tab: str, text: str, *, at: str | None = None, kind: str = "added") -> None:
    writer = ticket_service.writer_of(tab) if tab else ticket_entry.CLIENT_WRITER
    ticket_file.append(folder, ticket, ticket_entry.make_entry(kind, writer, text, at=at or ticket_service.now()))


def test_a_tab_is_given_the_tickets_it_holds_that_are_not_closed_and_no_other(ticket_env):
    mine, others, closed, waiting = (outside_ticket(title=name) for name in ("mine", "others", "closed", "waiting"))
    _hold(others, "ses_b")
    _hold(closed, "ses_a", status="closed")
    _hold(waiting, "ses_a", status="waiting")
    answer = _held()
    assert sorted(_ids(answer)) == sorted([mine, waiting]) and answer["tab"] == "ses_a" and answer["peer_unreachable"] == []
    assert _ids(_held("ses_b")) == [others] and _ids(_held("ses_c")) == []


def test_a_ticket_is_given_with_its_title_state_source_due_day_marks_next_step_and_last_time(ticket_env):
    ticket = run(ticket_service.open_ticket("ses_a", "Move the title", "Please move it.", operator_said=False,
                                            due="2000-01-01"))["id"]
    run(ticket_service.add("ses_b", ticket, "I looked at it\nand it is hard"))
    _hold(ticket, "ses_b")
    item = _held("ses_b")["tickets"][0]
    last = [entry for entry in ticket_file.read(ticket_env.tickets, ticket) if entry["kind"] == "added"][0]["at"]
    assert item == {"id": ticket, "title": "Move the title", "status": "open", "source": "tab", "due": "2000-01-01",
                    "marks": ["overdue"], "next": "I looked at it", "last_at": last, "written_since": None,
                    "writable": True}


def test_a_ticket_the_holder_opened_comes_from_itself_and_one_with_the_operators_words_from_the_operator(ticket_env):
    own = outside_ticket()
    said = run(ticket_service.open_ticket("ses_a", "Said", "Request", operator_said=True))["id"]
    sources = {ticket["id"]: ticket["source"] for ticket in _held()["tickets"]}
    assert sources == {own: "self", said: "operator"}


def test_a_ticket_whose_last_line_is_a_hand_over_has_the_text_of_the_line_before_as_its_next_step(ticket_env):
    ticket = outside_ticket()
    _line(ticket_env.tickets, ticket, "ses_a", "do the thing", kind="added")
    _line(ticket_env.tickets, ticket, "ses_a", "", kind="passed")
    _hold(ticket, "ses_b")
    assert _held("ses_b")["tickets"][0]["next"] == "do the thing"


# --- written since ---


def test_a_tab_has_written_since_a_time_when_a_line_of_its_own_is_at_or_after_it(ticket_env):
    ticket = outside_ticket()
    start = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    assert _held("ses_a", start)["tickets"][0]["written_since"] is False
    assert _held("ses_a", BEFORE)["tickets"][0]["written_since"] is True
    assert ticket_file.read(ticket_env.tickets, ticket)[0]["tab"] == "ses_a"


def test_a_line_of_another_tab_or_of_the_client_is_not_a_line_the_tab_wrote(ticket_env):
    ticket = outside_ticket()
    _hold(ticket, "ses_b")
    _line(ticket_env.tickets, ticket, "ses_c", "someone else wrote", kind="added")
    _line(ticket_env.tickets, ticket, "", "", kind="delivered")
    assert _held("ses_b", BEFORE)["tickets"][0]["written_since"] is False
    _line(ticket_env.tickets, ticket, "ses_b", "my own line")
    assert _held("ses_b", BEFORE)["tickets"][0]["written_since"] is True


def test_a_ticket_just_handed_over_is_not_written_since_until_the_new_holder_writes(ticket_env):
    ticket = outside_ticket()
    _hold(ticket, "ses_b")
    assert _held("ses_b", BEFORE)["tickets"][0]["written_since"] is False


def test_the_times_are_compared_as_times_whatever_offset_they_are_written_with(ticket_env):
    outside_ticket()
    now = datetime.now(timezone.utc)
    later_in_tokyo = (now + timedelta(minutes=5)).astimezone(timezone(timedelta(hours=9))).isoformat()
    earlier_in_tokyo = (now - timedelta(minutes=5)).astimezone(timezone(timedelta(hours=9))).isoformat()
    assert _held("ses_a", later_in_tokyo)["tickets"][0]["written_since"] is False
    assert _held("ses_a", earlier_in_tokyo)["tickets"][0]["written_since"] is True


# --- what the tab may read ---


def test_a_title_the_tab_may_not_read_is_not_given_and_only_the_two_lines_it_shows_are_judged(ticket_env):
    ticket = outside_ticket(title="a secret title")
    run(ticket_service.add("ses_a", ticket, "middle one"))
    run(ticket_service.add("ses_a", ticket, "a secret next step"))
    ticket_env.guard.use("read", read={"refuse_containing": "secret"})
    item = _held()["tickets"][0]
    assert (item["title"], item["next"]) == (None, ticket_entry.HIDDEN_TEXT)
    assert len(ticket_env.guard.calls("read")) == 2


def test_a_title_the_tab_may_read_is_given_with_one_judgement_for_a_ticket_of_one_line(ticket_env):
    outside_ticket(title="plain title")
    ticket_env.guard.use("read")
    assert _held()["tickets"][0]["title"] == "plain title"
    assert len(ticket_env.guard.calls("read")) == 1


# --- may the tab write there ---


def test_a_ticket_is_writable_when_the_tab_has_read_its_places_boundary(ticket_env):
    outside_ticket()
    ticket_env.guard.use("covers")
    assert _held()["tickets"][0]["writable"] is True
    ticket_env.guard.answer(covers={"refuse_sessions": ["conv-ses_a"]})
    assert _held()["tickets"][0]["writable"] is False


def test_a_check_that_cannot_run_makes_the_ticket_not_writable_and_does_not_stop_the_list(ticket_env):
    outside_ticket(title="still listed")
    ticket_env.guard.use("covers", covers={"status": 2})
    item = _held()["tickets"][0]
    assert (item["writable"], item["title"]) == (False, "still listed")


def test_a_ticket_whose_place_is_not_known_now_is_listed_without_a_title_and_not_writable(ticket_env):
    ticket = outside_ticket()
    _hold(ticket, "ses_a", place_key="f" * 16)
    item = _held()["tickets"][0]
    assert (item["id"], item["title"], item["writable"], item["last_at"], item["next"]) == (ticket, None, False, "", "")


# --- the other machine ---


def _peer_ticket(ticket: str = "company-261120-01", **row) -> dict:
    return {"id": ticket, "opened_at": "2026-11-20T01:00:00.000+00:00", "status": "open", "wants": None, "holder": "ses_a",
            "opener": "company:ses_x", "origin": "self", "due": None, **row}


def _peer_shown(*lines: dict) -> tuple[int, dict]:
    return 200, {"ok": True, "entries": list(lines)}


def _opened(title: str = "Peer title") -> dict:
    return {"kind": "opened", "at": "2026-11-20T01:00:00.000+00:00", "tab": "company:ses_x", "text": "Peer request", "title": title}


def test_the_other_machines_ticket_held_by_the_tab_is_listed_with_what_that_machine_lets_the_tab_read(relay_env):
    relay_env.peer_says[PEER_LIST] = (200, {"ok": True, "home": "company", "tickets": [
        _peer_ticket(origin="operator", due="2000-01-01"), _peer_ticket("company-261120-02", holder="ses_b"),
        _peer_ticket("company-261120-03", status="closed")]})
    relay_env.peer_says["/agent-messages/tickets/company-261120-01"] = _peer_shown(
        _opened(), {"kind": "added", "at": "2026-11-20T02:00:00.000+00:00", "tab": "ses_a", "text": "on it\nmore"})
    answer = _held("ses_a", BEFORE)
    assert answer["peer_unreachable"] == [] and _ids(answer) == ["company-261120-01"]
    assert answer["tickets"][0] == {"id": "company-261120-01", "title": "Peer title", "status": "open", "source": "operator",
                                    "due": "2000-01-01", "marks": ["overdue"], "next": "on it", "last_at": "2026-11-20T02:00:00.000+00:00",
                                    "written_since": True, "writable": True}
    assert [url.split("?")[0] for url, _payload in relay_env.carried] == [
        "http://peer.test/agent-messages/tickets", "http://peer.test/agent-messages/tickets/company-261120-01"]


def test_the_other_machines_ticket_is_from_another_tab_and_not_written_since_when_only_that_tab_wrote(relay_env):
    relay_env.peer_says[PEER_LIST] = (200, {"ok": True, "tickets": [_peer_ticket()]})
    relay_env.peer_says["/agent-messages/tickets/company-261120-01"] = _peer_shown(_opened())
    item = _held("ses_a", BEFORE)["tickets"][0]
    assert (item["source"], item["written_since"], item["next"]) == ("tab", False, "Peer request")


def test_a_line_the_other_machine_withheld_is_no_line_of_a_tab_and_gives_no_next_step(relay_env):
    relay_env.peer_says[PEER_LIST] = (200, {"ok": True, "tickets": [_peer_ticket()]})
    relay_env.peer_says["/agent-messages/tickets/company-261120-01"] = _peer_shown(
        {"kind": "operator", "at": "2026-11-20T01:00:01.000+00:00", "hidden": True, "text": ticket_entry.WITHHELD_TEXT})
    item = _held("ses_a")["tickets"][0]
    assert (item["title"], item["next"], item["last_at"]) == (None, "", "")


def test_a_machine_that_does_not_answer_is_named_and_the_tickets_of_this_machine_are_still_listed(relay_env):
    ticket = outside_ticket()
    relay_env.peer_says[PEER_LIST] = relay_env.down
    answer = _held()
    assert _ids(answer) == [ticket] and answer["peer_unreachable"] == ["company"]


def test_a_machine_that_answers_with_something_that_is_not_a_list_is_named_as_not_answering(relay_env):
    relay_env.peer_says[PEER_LIST] = (500, {})
    assert _held()["peer_unreachable"] == ["company"]


def test_a_machine_whose_ticket_cannot_be_read_is_left_out_whole_and_named(relay_env):
    relay_env.peer_says[PEER_LIST] = (200, {"ok": True, "tickets": [_peer_ticket()]})
    relay_env.peer_says["/agent-messages/tickets/company-261120-01"] = relay_env.down
    answer = _held()
    assert answer["tickets"] == [] and answer["peer_unreachable"] == ["company"]


def test_a_machine_the_tabs_account_may_not_talk_to_is_not_asked(relay_env):
    relay_env.configure("home", "company", accounts=["nobody"])
    answer = _held()
    assert answer["peer_unreachable"] == [] and relay_env.carried == []
