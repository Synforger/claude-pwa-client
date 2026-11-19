"""The doors of the tickets: the forms, the values they refuse, the answers, and that they answer this machine only."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import backend.routes.tickets as ticket_routes
from backend.tests.tickets.samples import ticket_env  # noqa: F401
from backend.tickets import ticket_index, ticket_pass


@pytest.fixture
def client(ticket_env, monkeypatch):
    async def deliver(tab_id, text):
        return {"ok": True}

    monkeypatch.setattr(ticket_pass, "deliver_or_keep", deliver)
    monkeypatch.setattr(ticket_pass, "tab_reachable", lambda tab_id: True)
    app = FastAPI()
    app.include_router(ticket_routes.router)
    return TestClient(app)


def _open(client, **fields) -> str:
    return client.post("/tickets", data={"from": "ses_a", "title": "Title", "text": "Request", **fields}).json()["id"]


def _error(response) -> tuple[int, str]:
    return response.status_code, response.json()["detail"]["code"]


def test_a_ticket_is_opened_with_the_tab_the_title_and_the_text(client):
    answer = client.post("/tickets", data={"from": "ses_a", "title": "Title", "text": "Request"})
    assert answer.status_code == 200
    assert answer.json() == {"ok": True, "id": answer.json()["id"], "place_outside": True, "operator_said": False}


def test_the_operators_words_go_in_only_when_asked_for(client):
    said = client.post("/tickets", data={"from": "ses_a", "title": "T", "text": "x", "operator_said": "true"}).json()
    assert said["operator_said"] is True
    shown = client.get(f"/tickets/{said['id']}", params={"reader": "ses_b"}).json()
    assert [entry["kind"] for entry in shown["entries"]] == ["opened", "operator"]


def test_an_entry_an_ask_and_a_close_change_the_state_and_are_read_back(client):
    ticket = _open(client)
    assert client.post(f"/tickets/{ticket}/entries", data={"from": "ses_b", "text": "step"}).json()["status"] == "open"
    asked = client.post(f"/tickets/{ticket}/asks", data={"from": "ses_a", "kind": "decide", "text": "A or B?", "recommend": "A"})
    assert asked.json() == {"ok": True, "id": ticket, "status": "waiting-operator"}
    assert client.post(f"/tickets/{ticket}/close", data={"from": "ses_a", "text": "done"}).json()["status"] == "closed"
    shown = client.get(f"/tickets/{ticket}", params={"reader": "ses_c"}).json()
    assert [entry["kind"] for entry in shown["entries"]] == ["opened", "added", "asked", "closed"]
    assert shown["entries"][2]["recommend"] == "A"


def test_a_close_needs_no_text(client):
    ticket = _open(client)
    assert client.post(f"/tickets/{ticket}/close", data={"from": "ses_a"}).json()["status"] == "closed"


def test_a_blank_recommendation_is_none(client):
    ticket = _open(client)
    client.post(f"/tickets/{ticket}/asks", data={"from": "ses_a", "kind": "report", "text": "done", "recommend": "  "})
    entries = client.get(f"/tickets/{ticket}", params={"reader": "ses_a"}).json()["entries"]
    assert "recommend" not in entries[-1]


def test_a_ticket_is_passed_by_the_tabs_id_or_name(client):
    ticket = _open(client)
    assert client.post(f"/tickets/{ticket}/pass", data={"from": "ses_a", "to": "notes"}).json() == {
        "ok": True, "id": ticket, "to": "ses_b"}
    assert ticket_index.get(ticket).holder == "ses_b"


def test_the_listing_gives_the_titles(client):
    _open(client, title="Listed")
    assert [row["title"] for row in client.get("/tickets").json()["tickets"]] == ["Listed"]


@pytest.mark.parametrize(("path", "form", "expected"), [
    ("/tickets", {"from": "ses_a", "title": "  ", "text": "x"}, (400, "ticket_empty")),
    ("/tickets", {"from": "ses_a", "title": "t", "text": "\n"}, (400, "ticket_empty")),
    ("/tickets", {"from": "nobody", "title": "t", "text": "x"}, (400, "ticket_unknown_sender")),
    ("/tickets/home-261119-01/entries", {"from": "ses_a", "text": " "}, (400, "ticket_empty")),
    ("/tickets/home-261119-01/entries", {"from": "nobody", "text": "x"}, (400, "ticket_unknown_sender")),
    ("/tickets/home-261119-01/entries", {"from": "ses_a", "text": "x"}, (404, "ticket_unknown")),
    ("/tickets/home-261119-01/asks", {"from": "ses_a", "kind": "later", "text": "x"}, (400, "ticket_bad_kind")),
    ("/tickets/home-261119-01/asks", {"from": "ses_a", "kind": "decide", "text": ""}, (400, "ticket_empty")),
    ("/tickets/home-261119-01/close", {"from": "ses_a"}, (404, "ticket_unknown")),
    ("/tickets/home-261119-01/pass", {"from": "ses_a", "to": "ses_b"}, (404, "ticket_unknown")),
    ("/tickets/home-261119-01/pass", {"from": "ses_a", "to": " "}, (400, "ticket_empty")),
    ("/tickets/home-261119-01/pass", {"from": "ses_a"}, (400, "ticket_empty")),
    ("/tickets", {"from": "ses_a", "title": "t"}, (400, "ticket_empty")),
    ("/tickets/home-261119-01/asks", {"from": "ses_a", "text": "x"}, (400, "ticket_bad_kind")),
])
def test_a_bad_form_is_refused_with_its_code_before_anything_is_written(client, ticket_env, path, form, expected):
    assert _error(client.post(path, data=form)) == expected
    assert ticket_index.rows() == {}


def test_a_text_that_is_not_an_id_is_an_unknown_ticket_not_a_file_name(client):
    assert _error(client.get("/tickets/home-261119-01.jsonl", params={"reader": "ses_a"})) == (404, "ticket_unknown")
    assert _error(client.get("/tickets/not-an-id", params={"reader": "ses_a"})) == (404, "ticket_unknown")


def test_reading_needs_a_reader_that_is_a_tab(client):
    ticket = _open(client)
    assert _error(client.get(f"/tickets/{ticket}", params={"reader": "nobody"})) == (400, "ticket_unknown_sender")
    assert client.get(f"/tickets/{ticket}").status_code == 422


def test_a_closed_ticket_answers_409_with_its_code(client):
    ticket = _open(client)
    client.post(f"/tickets/{ticket}/close", data={"from": "ses_a"})
    assert _error(client.post(f"/tickets/{ticket}/entries", data={"from": "ses_a", "text": "x"})) == (409, "ticket_closed")


def test_a_ticket_waiting_for_the_operator_answers_409_to_a_pass(client):
    ticket = _open(client)
    client.post(f"/tickets/{ticket}/asks", data={"from": "ses_a", "kind": "mac", "text": "plug it in"})
    assert _error(client.post(f"/tickets/{ticket}/pass", data={"from": "ses_a", "to": "ses_b"})) == (409, "ticket_waiting_operator")


def test_no_door_answers_a_call_from_another_machine(ticket_env):
    app = FastAPI()
    app.include_router(ticket_routes.router)
    remote = TestClient(app, client=("203.0.113.9", 50000))
    calls = [remote.post("/tickets", data={"from": "ses_a", "title": "t", "text": "x"}),
             remote.post("/tickets/home-261119-01/entries", data={"from": "ses_a", "text": "x"}),
             remote.post("/tickets/home-261119-01/asks", data={"from": "ses_a", "kind": "mac", "text": "x"}),
             remote.post("/tickets/home-261119-01/answer", json={"asked_at": "x", "text": "x"}),
             remote.post("/tickets/home-261119-01/close", data={"from": "ses_a"}),
             remote.post("/tickets/home-261119-01/pass", data={"from": "ses_a", "to": "ses_b"}),
             remote.get("/tickets/home-261119-01", params={"reader": "ses_a"}), remote.get("/tickets")]
    assert [_error(call) for call in calls] == [(403, "ticket_local_only")] * 8
    assert ticket_index.rows() == {}

