"""A command on a ticket the other machine keeps: it is judged here, carried to that machine's backend and its answer comes
back as it was; nothing is kept for later, and `ask` is refused."""
from __future__ import annotations

import sys
import urllib.parse

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.peers import outbox_store
from backend.routes import tickets as ticket_routes
from backend.tests.async_run import run
from backend.tests.tickets.samples import PEER_URL, relay_env  # noqa: F401
from backend.tests.tickets.samples import ticket_env  # noqa: F401
from backend.tickets import ticket_relay

REMOTE = "home-261119-07"       # kept on `home`; this machine is `company`


@pytest.fixture
def company(relay_env):
    """This machine is `company`, and `home` keeps the tickets."""
    relay_env.configure("company", "home")
    return relay_env


@pytest.fixture
def client(company):
    app = FastAPI()
    app.include_router(ticket_routes.router)
    return TestClient(app)


def _error(response) -> tuple[int, str]:
    return response.status_code, response.json()["detail"]["code"]


def _error_of(call) -> str:
    with pytest.raises(HTTPException) as refused:
        call()
    return refused.value.detail["code"]


def test_the_home_of_a_ticket_is_the_machine_at_the_head_of_its_id(company):
    assert ticket_relay.home_of("company-261119-01") is None
    home = ticket_relay.home_of(REMOTE)
    assert home.name == "home" and home.peer["url"] == PEER_URL


def test_a_ticket_of_a_machine_that_is_not_configured_is_unknown(company):
    assert _error_of(lambda: ticket_relay.home_of("office-261119-01")) == "ticket_unknown"


def test_add_carries_the_text_and_the_tab_to_the_home_and_gives_its_answer_back(company, client):
    company.peer_says["/entries"] = (200, {"ok": True, "id": REMOTE, "status": "open"})
    answer = client.post(f"/tickets/{REMOTE}/entries", data={"from": "ses_a", "text": "I did it"})
    assert (answer.status_code, answer.json()) == (200, {"ok": True, "id": REMOTE, "status": "open"})
    assert company.carried == [(f"{PEER_URL}/agent-messages/tickets/{REMOTE}/entries",
                                {"from_session": "ses_a", "from_title": "client work", "text": "I did it"})]


def test_close_carries_the_last_word_and_may_have_none(company, client):
    client.post(f"/tickets/{REMOTE}/close", data={"from": "ses_a", "text": "done"})
    client.post(f"/tickets/{REMOTE}/close", data={"from": "ses_a"})
    assert [payload["text"] for _url, payload in company.carried] == ["done", ""]
    assert all(url.endswith(f"/{REMOTE}/close") for url, _payload in company.carried)


def test_show_asks_the_home_with_the_tab_as_the_reader_and_prints_what_it_answers(company, client):
    body = {"ok": True, "id": REMOTE, "status": "open", "holder": "home:ses_h", "entries": [], "home": "home"}
    company.peer_says[REMOTE] = (200, body)
    answer = client.get(f"/tickets/{REMOTE}", params={"reader": "ses_a"})
    assert answer.json() == body
    assert company.carried == [(f"{PEER_URL}/agent-messages/tickets/{REMOTE}?reader=ses_a", None)]


def test_pass_carries_the_destination_as_the_tab_spelled_it(company, client):
    client.post(f"/tickets/{REMOTE}/pass", data={"from": "ses_a", "to": "notes"})
    client.post(f"/tickets/{REMOTE}/pass", data={"from": "ses_a", "to": "home:slides"})
    assert [payload for _url, payload in company.carried] == [
        {"from_session": "ses_a", "from_title": "client work", "to_machine": "company", "to": "notes"},
        {"from_session": "ses_a", "from_title": "client work", "to_machine": "home", "to": "slides"}]
    assert all(url == f"{PEER_URL}/agent-messages/tickets/{REMOTE}/pass" for url, _payload in company.carried)


def test_ask_is_refused_for_a_ticket_of_the_other_machine_and_nothing_is_carried(company, client):
    answer = client.post(f"/tickets/{REMOTE}/asks", data={"from": "ses_a", "kind": "decide", "text": "A or B?"})
    assert _error(answer) == (409, "ticket_ask_elsewhere")
    assert company.carried == []


def test_the_operators_doors_are_refused_for_a_ticket_of_the_other_machine_and_nothing_is_carried(company, client):
    """The operator reads and answers a ticket on the screen of the machine that keeps it, so the doors of the screen work
    on this machine's tickets only."""
    for answer in (client.get(f"/tickets/{REMOTE}/answer"),
                   client.post(f"/tickets/{REMOTE}/answer/holder", json={"to": "ses_b"}),
                   client.post(f"/tickets/{REMOTE}/answer/seen")):
        assert _error(answer) == (409, "ticket_elsewhere")
    assert answer.json()["detail"]["params"]["peer"] == "home"
    assert company.carried == []


def test_a_holder_to_hand_to_must_be_given_as_a_non_empty_text(company, client):
    for body in ({}, {"to": "  "}, {"to": 3}):
        assert _error(client.post("/tickets/company-261119-01/answer/holder", json=body)) == (400, "ticket_empty")


def test_a_machine_that_does_not_answer_is_503_and_nothing_is_kept(company, client):
    company.peer_says["/entries"] = company.down
    answer = client.post(f"/tickets/{REMOTE}/entries", data={"from": "ses_a", "text": "I did it"})
    assert _error(answer) == (503, "ticket_peer_down")
    assert "戻ってからやり直してください" in answer.json()["detail"]["message"]
    assert "済んでいるかもしれません" not in answer.json()["detail"]["message"]
    assert not outbox_store.pending("home")


def test_a_call_that_was_sent_and_got_no_answer_says_the_command_may_have_been_done(company, client):
    company.peer_says["/close"] = TimeoutError("read timed out")
    answer = client.post(f"/tickets/{REMOTE}/close", data={"from": "ses_a", "text": "done"})
    assert _error(answer) == (503, "ticket_peer_down")
    assert "済んでいるかもしれません" in answer.json()["detail"]["message"]


def test_the_homes_refusal_comes_back_with_its_status_and_code(company, client):
    company.peer_says["/entries"] = (403, {"detail": {"code": "ticket_inside_boundary", "message": "inside"}})
    assert _error(client.post(f"/tickets/{REMOTE}/entries", data={"from": "ses_a", "text": "x"})) == (403, "ticket_inside_boundary")


def test_a_refusal_with_no_code_is_the_peer_failed_and_says_to_check_first(company, client):
    company.peer_says["/entries"] = (500, {})
    answer = client.post(f"/tickets/{REMOTE}/entries", data={"from": "ses_a", "text": "x"})
    assert _error(answer) == (500, "ticket_peer_failed") and "確かめてください" in answer.json()["detail"]["message"]


def test_a_text_that_leaves_is_judged_as_a_message_to_the_home_and_a_refusal_carries_nothing(company, client):
    company.configure("company", "home", agent_message_check=[sys.executable, "-c", "import sys; sys.exit(1)"])
    answer = client.post(f"/tickets/{REMOTE}/entries", data={"from": "ses_a", "text": "secret"})
    assert _error(answer) == (403, "agent_message_refused") and company.carried == []


def test_the_judgement_is_told_the_machine_and_the_ticket_as_the_receiver(company, client, tmp_path):
    log = tmp_path / "session.txt"
    script = f"import sys; open({str(log)!r}, 'w').write(sys.argv[1])"
    company.configure("company", "home", agent_message_check=[sys.executable, "-c", script, "{session}"])
    client.post(f"/tickets/{REMOTE}/entries", data={"from": "ses_a", "text": "fine"})
    assert log.read_text() == f"home:{REMOTE}"
    log.unlink()
    client.post(f"/tickets/{REMOTE}/close", data={"from": "ses_a"})      # no last word: nothing to judge
    assert not log.exists() and len(company.carried) == 2


def test_a_tab_whose_account_may_not_talk_to_that_machine_carries_nothing(company, client, monkeypatch):
    company.configure("company", "home", accounts=["work"])
    answer = client.post(f"/tickets/{REMOTE}/entries", data={"from": "ses_a", "text": "x"})
    assert _error(answer) == (403, "agent_message_peer_not_allowed") and company.carried == []


def test_a_ticket_of_this_machine_is_not_carried(company, client):
    answer = client.post("/tickets", data={"from": "ses_a", "title": "T", "text": "x"})
    ticket = answer.json()["id"]
    assert ticket.startswith("company-")
    assert client.post(f"/tickets/{ticket}/entries", data={"from": "ses_a", "text": "more"}).status_code == 200
    assert company.carried == []


def test_a_ticket_of_a_machine_that_is_not_configured_is_404_on_every_door(company, client):
    ticket = "office-261119-01"
    answers = [client.post(f"/tickets/{ticket}/entries", data={"from": "ses_a", "text": "x"}),
               client.post(f"/tickets/{ticket}/asks", data={"from": "ses_a", "kind": "mac", "text": "x"}),
               client.post(f"/tickets/{ticket}/close", data={"from": "ses_a"}),
               client.post(f"/tickets/{ticket}/pass", data={"from": "ses_a", "to": "ses_b"}),
               client.get(f"/tickets/{ticket}", params={"reader": "ses_a"})]
    assert [_error(answer) for answer in answers] == [(404, "ticket_unknown")] * 5 and company.carried == []


@pytest.mark.parametrize("answer, expected", [
    ((200, {"tabs": [{"id": "ses_x"}, {"id": "ses_y"}]}), True),
    ((200, {"tabs": [{"id": "ses_y"}]}), False),
    ((500, {}), None),
    ((200, {"tabs": "x"}), None),
])
def test_a_tab_of_the_other_machine_is_gone_only_when_that_machine_answers_and_does_not_list_it(company, answer, expected):
    company.peer_says["/agent-messages/tabs"] = answer
    assert run(ticket_relay.holder_listed("home:ses_x")) is expected


def test_a_machine_that_does_not_answer_or_is_not_configured_has_its_tabs_taken_to_be_there(company):
    company.peer_says["/agent-messages/tabs"] = company.down
    assert run(ticket_relay.holder_listed("home:ses_x")) is None
    assert run(ticket_relay.holder_listed("office:ses_x")) is None
    assert urllib.parse.urlsplit(company.carried[0][0]).path == "/agent-messages/tabs"
