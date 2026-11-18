"""Opening a ticket: its id, where it is kept, what the index knows of it, and the operator's words in its second line."""
from __future__ import annotations

import json
import socket
from datetime import date

import pytest
from fastapi import HTTPException

import backend._common.config as config_mod
from backend.tests.async_run import run
from backend.tests.tickets.samples import ticket_env, write_config  # noqa: F401
from backend.tickets import ticket_file, ticket_index, ticket_places, ticket_service

TODAY = f"{date.today():%y%m%d}"


def _open(title="Move the title", text="Please move the title up.", operator_said=False):
    return run(ticket_service.open_ticket("ses_a", title, text, operator_said=operator_said))


def test_without_a_guard_a_ticket_is_kept_outside_every_boundary(ticket_env):
    answer = _open()
    assert answer == {"ok": True, "id": f"home-{TODAY}-01", "place_outside": True, "operator_said": False}
    entries = ticket_file.read(ticket_env.tickets, answer["id"])
    assert [(entry["kind"], entry["tab"], entry["tab_title"], entry["tier"]) for entry in entries] == [
        ("opened", "ses_a", "client work", "projects/AP")]
    assert (entries[0]["title"], entries[0]["text"]) == ("Move the title", "Please move the title up.")


def test_the_numbers_of_a_machine_and_day_count_from_01(ticket_env):
    assert [_open()["id"] for _ in range(3)] == [f"home-{TODAY}-0{n}" for n in (1, 2, 3)]


def test_a_number_that_is_taken_by_the_index_or_by_a_file_left_behind_is_skipped(ticket_env):
    ticket_env.tickets.mkdir(parents=True)
    (ticket_env.tickets / f"home-{TODAY}-01.jsonl").write_text("")            # a file the index never heard of
    ticket_index.put(f"home-{TODAY}-02", ticket_index.IndexRow("k", "ses_a", "ses_a", "open", None))
    assert _open()["id"] == f"home-{TODAY}-03"


def test_the_machine_name_comes_from_the_configuration_and_else_from_the_host(ticket_env):
    write_config(ticket_env.guard._monkeypatch, ticket_env.root, machine_name="office")
    assert _open()["id"] == f"office-{TODAY}-01"
    write_config(ticket_env.guard._monkeypatch, ticket_env.root)
    assert config_mod.MACHINE_NAME == socket.gethostname().split(".")[0]


def test_the_index_holds_the_place_the_holder_the_opener_the_state_and_what_is_wanted_and_no_title_or_text(ticket_env):
    ticket = _open(title="A secret title", text="A secret body")["id"]
    raw = (ticket_env.tickets / "index.json").read_text(encoding="utf-8")
    assert "secret" not in raw and str(ticket_env.tickets) not in raw
    assert json.loads(raw) == {ticket: {"place_key": ticket_places.outside_key(), "holder": "ses_a", "opener": "ses_a",
                                        "status": "open", "wants": None}}


def test_the_operator_words_are_the_second_line_as_the_record_has_them(ticket_env):
    ticket = _open(operator_said=True)
    assert ticket["operator_said"] is True and "operator_said_left_out" not in ticket
    opened, operator = ticket_file.read(ticket_env.tickets, ticket["id"])
    assert (operator["kind"], operator["text"], operator["typed_in"], operator["tab"]) == (
        "operator", "please fix the title", "ses_a", "ses_a")
    assert opened["kind"] == "opened"


def test_when_the_work_did_not_start_from_the_operator_the_ticket_opens_without_the_words_and_says_why(ticket_env, monkeypatch):
    monkeypatch.setattr(ticket_service, "last_operator_text", lambda record: None)
    answer = _open(operator_said=True)
    assert (answer["operator_said"], answer["operator_said_left_out"]) == (False, "no_operator_words")
    assert [entry["kind"] for entry in ticket_file.read(ticket_env.tickets, answer["id"])] == ["opened"]


def test_the_operator_words_are_not_looked_for_unless_asked(ticket_env, monkeypatch):
    monkeypatch.setattr(ticket_service, "last_operator_text", lambda record: pytest.fail("the record was read"))
    assert _open()["operator_said"] is False


def test_a_ticket_that_is_not_in_the_index_is_unknown(ticket_env):
    with pytest.raises(HTTPException) as refused:
        ticket_service.row_of("home-261119-09")
    assert refused.value.detail["code"] == "ticket_unknown"
