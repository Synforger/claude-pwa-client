"""A stop of the backend ends the waits of the ticket doors (`tickets/ticket_stop.py`): uvicorn gives the responses 3 seconds,
and a door that waits for the guard's command or for the other machine used to be cut at that time, with a traceback in the log
and a bare 500 for `tabs`. The door now answers what is true of the stage the stop came in: a read changed nothing
(`ticket_backend_stopping`), a write that stopped before anything was written (`ticket_not_sent`) or one whose call to another
machine or to a tab was made (`ticket_unconfirmed`)."""
from __future__ import annotations

import asyncio
import logging
import time
from unittest.mock import AsyncMock

import httpx2
import pytest
from fastapi import FastAPI, HTTPException

from backend._internal import stop_signal
from backend._internal.stop_signal import BackendStopping
from backend.peers import peer_call
from backend.routes import tickets as ticket_routes
from backend.tests.async_run import run
from backend.tests.tickets.samples import answered_ticket, outside_ticket, queued, refusal, relay_env  # noqa: F401
from backend.tests.tickets.samples import delivery_env, ticket_env  # noqa: F401
from backend.tickets import (answer_delivery, ticket_checks, ticket_file, ticket_index, ticket_pass, ticket_relay, ticket_return,
                             ticket_service, ticket_stop)

#: How long a guard command or a call to the other machine takes when nothing ends it: much longer than a stop needs
RUNS_ON_SEC = 2.5
#: The stop comes this long after the wait began; the whole request must end within `ENDS_WITHIN_SEC` of it
STOP_AFTER_SEC = 0.05
ENDS_WITHIN_SEC = 1.0
REMOTE = "home-261119-07"       # kept on `home`; this machine is `company`
STOPPING = "backend_stopping"
READ = (503, "ticket_backend_stopping")
NOT_SENT = (503, "ticket_not_sent")
UNCONFIRMED = (500, "ticket_unconfirmed")


@pytest.fixture(autouse=True)
def running(monkeypatch):
    """The backend runs when a test begins, and again for the tests after it."""
    monkeypatch.setattr(stop_signal, "_stopping", False)


async def _door(method: str, path: str, *, stop: bool = True, **fields) -> tuple[tuple[int, str], dict, float]:
    """Call a door of the tickets and, when `stop`, ask the backend to stop shortly after. → ((status, code), the detail, the
    seconds the call took)."""
    app = FastAPI()
    app.include_router(ticket_routes.router)
    if stop:
        asyncio.get_running_loop().call_later(STOP_AFTER_SEC, stop_signal.end_work)
    began = time.monotonic()
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, path, **({"params": fields} if method == "GET" else {"data": fields}))
    detail = response.json().get("detail", {})
    return (response.status_code, detail.get("code")), detail, time.monotonic() - began


def _ends_within_the_grace(took: float) -> None:
    assert took < ENDS_WITHIN_SEC, "the door went on to the end of its wait"


@pytest.fixture
def slow_peer(relay_env, monkeypatch):
    """This machine is `company` and the other machine, `home`, keeps `REMOTE`; every call to it takes `RUNS_ON_SEC`."""
    relay_env.configure("company", "home")

    def slow(url, payload, timeout):
        time.sleep(RUNS_ON_SEC)
        return 200, {"ok": True, "id": REMOTE, "status": "open"}

    monkeypatch.setattr(peer_call, "_call_peer", slow)
    return relay_env


def refusal_with_reason(status: int, code: str) -> HTTPException:
    """The error the delivery of a message raises when the stop ends it (`routes/agent_messages.py: refuse_by_stop`)."""
    return HTTPException(status, detail={"code": code, "message": code, "params": {"reason": STOPPING}})


def _slow_guard(env, *modes: str) -> None:
    """The guard's commands of `modes` take `RUNS_ON_SEC` to answer, and pass."""
    env.guard.use(*modes, **{mode: {"sleep": RUNS_ON_SEC} for mode in modes})


# --- a guard command is a wait the stop ends ---


def test_a_guard_command_ends_at_the_stop_and_the_command_is_not_waited_for(ticket_env):
    _slow_guard(ticket_env, "covers")

    async def check():
        asyncio.get_running_loop().call_later(STOP_AFTER_SEC, stop_signal.end_work)
        began = time.monotonic()
        with pytest.raises(BackendStopping):
            await ticket_checks.check_covers("ses_a", ticket_env.tickets)
        return time.monotonic() - began

    _ends_within_the_grace(run(check()))


def test_a_guard_command_asked_after_the_stop_is_not_started(ticket_env):
    ticket_env.guard.use("covers")
    stop_signal.end_work()
    with pytest.raises(BackendStopping):
        run(ticket_checks.check_covers("ses_a", ticket_env.tickets))
    assert ticket_env.guard.calls() == []


# --- the doors that read: nothing is changed, send the same command again ---


def test_show_ends_at_the_stop_and_says_nothing_was_changed(ticket_env):
    ticket = outside_ticket()
    _slow_guard(ticket_env, "read")
    (code, detail, took) = run(_door("GET", f"/tickets/{ticket}", reader="ses_b"))
    assert code == READ and detail["params"]["reason"] == STOPPING
    assert "何も変わっていません" in detail["message"] and "書けて" not in detail["message"]
    _ends_within_the_grace(took)


def test_held_ends_at_the_stop_while_it_waits_for_the_guard(ticket_env):
    """The incident: `tabs ticket mine` was cut at the stop with a bare 500."""
    outside_ticket()
    _slow_guard(ticket_env, "read", "covers")
    (code, detail, took) = run(_door("GET", "/tickets/held", tab="ses_a"))
    assert code == READ and detail["params"]["reason"] == STOPPING
    _ends_within_the_grace(took)


def test_a_read_of_a_ticket_of_the_other_machine_ends_at_the_stop(slow_peer):
    (code, _detail, took) = run(_door("GET", f"/tickets/{REMOTE}", reader="ses_a"))
    assert code == READ
    _ends_within_the_grace(took)


# --- the doors that write: before the write nothing changed, after the call it may have ---


@pytest.mark.parametrize("path, fields", [
    ("/entries", {"from": "ses_a", "text": "step"}),
    ("/close", {"from": "ses_a", "text": "done"}),
    ("/asks", {"from": "ses_a", "kind": "decide", "text": "A or B?"}),
])
def test_a_write_stopped_while_the_guard_judges_it_wrote_nothing(ticket_env, path, fields):
    ticket = outside_ticket()
    before = ticket_file.read(ticket_env.tickets, ticket)
    _slow_guard(ticket_env, "covers", "write")
    (code, detail, took) = run(_door("POST", f"/tickets/{ticket}{path}", **fields))
    assert code == NOT_SENT and detail["params"]["reason"] == STOPPING
    assert ticket_file.read(ticket_env.tickets, ticket) == before and ticket_index.get(ticket).status == "open"
    _ends_within_the_grace(took)


def test_a_ticket_is_not_opened_when_the_stop_comes_while_the_guard_names_its_place(ticket_env):
    _slow_guard(ticket_env, "place", "write")
    (code, _detail, took) = run(_door("POST", "/tickets", **{"from": "ses_a", "title": "Title", "text": "Request"}))
    assert code == NOT_SENT and ticket_index.rows() == {}
    _ends_within_the_grace(took)


def test_a_pass_stopped_while_the_guard_judges_it_leaves_the_ticket_with_its_holder(ticket_env):
    ticket = outside_ticket()
    _slow_guard(ticket_env, "covers")
    (code, _detail, took) = run(_door("POST", f"/tickets/{ticket}/pass", **{"from": "ses_a", "to": "ses_b"}))
    assert code == NOT_SENT and ticket_index.get(ticket).holder == "ses_a"
    _ends_within_the_grace(took)


def test_a_write_asked_after_the_stop_is_not_started(ticket_env):
    ticket = outside_ticket()
    ticket_env.guard.use("covers")
    before = ticket_file.read(ticket_env.tickets, ticket)
    stop_signal.end_work()
    (code, _detail, _took) = run(_door("POST", f"/tickets/{ticket}/entries", stop=False, **{"from": "ses_a", "text": "step"}))
    assert code == NOT_SENT and ticket_file.read(ticket_env.tickets, ticket) == before


def test_a_local_write_is_not_cut_by_a_stop_that_comes_once_the_guard_has_judged(ticket_env, monkeypatch):
    """The write is a few file operations: it is done, and the sender is told it was, whatever the stop does meanwhile."""
    ticket = outside_ticket()
    ticket_env.guard.use("covers")
    original = ticket_service.write_entry

    def stopped_during_the_write(*args, **options):
        stop_signal.end_work()
        return original(*args, **options)

    monkeypatch.setattr(ticket_service, "write_entry", stopped_during_the_write)
    (code, _detail, _took) = run(_door("POST", f"/tickets/{ticket}/entries", stop=False, **{"from": "ses_a", "text": "step"}))
    assert code == (200, None) and [entry["kind"] for entry in ticket_file.read(ticket_env.tickets, ticket)] == ["opened", "added"]


def test_a_write_to_the_other_machine_cut_by_the_stop_may_have_been_done(slow_peer):
    (code, detail, took) = run(_door("POST", f"/tickets/{REMOTE}/entries", **{"from": "ses_a", "text": "I did it"}))
    assert code == UNCONFIRMED and detail["params"]["reason"] == STOPPING and "tabs ticket show" in detail["message"]
    _ends_within_the_grace(took)


def test_a_write_to_the_other_machine_asked_after_the_stop_was_not_sent(relay_env):
    relay_env.configure("company", "home")
    stop_signal.end_work()
    (code, _detail, _took) = run(_door("POST", f"/tickets/{REMOTE}/entries", stop=False, **{"from": "ses_a", "text": "I did it"}))
    assert code == NOT_SENT and relay_env.carried == []


@pytest.mark.parametrize("operation, may_have_been_done", [("add", True), ("close", True), ("pass", True), ("notify", True),
                                                          ("show", False)])
def test_only_a_call_that_changes_the_other_machines_ticket_may_have_been_made_when_the_stop_cuts_it(
        slow_peer, operation, may_have_been_done):
    home = ticket_relay.home_of(REMOTE)

    async def carry():
        asyncio.get_running_loop().call_later(STOP_AFTER_SEC, stop_signal.end_work)
        with pytest.raises(BackendStopping) as stopped:
            await ticket_relay._carry(operation, home.name, home.peer, "/path", {}, REMOTE)
        return stopped.value

    assert isinstance(run(carry()), ticket_stop.StoppedAfterSending) is may_have_been_done


# --- what the delivery of a notice says at a stop is said in the ticket's words ---


def test_a_pass_whose_notice_was_not_typed_before_the_stop_is_not_sent(ticket_env, monkeypatch):
    ticket = outside_ticket()

    async def stopped(tab_id, text):
        raise refusal_with_reason(503, "agent_message_not_sent")

    monkeypatch.setattr(ticket_pass, "deliver_or_keep", stopped)
    monkeypatch.setattr(ticket_pass, "tab_reachable", AsyncMock(return_value=True))
    (code, detail, _took) = run(_door("POST", f"/tickets/{ticket}/pass", stop=False, **{"from": "ses_a", "to": "ses_b"}))
    assert code == NOT_SENT and detail["params"]["reason"] == STOPPING and ticket_index.get(ticket).holder == "ses_a"


def test_a_pass_whose_notice_may_have_been_typed_before_the_stop_may_have_been_done(ticket_env, monkeypatch):
    ticket = outside_ticket()

    async def stopped(tab_id, text):
        raise refusal_with_reason(500, "agent_message_unconfirmed")

    monkeypatch.setattr(ticket_pass, "deliver_or_keep", stopped)
    monkeypatch.setattr(ticket_pass, "tab_reachable", AsyncMock(return_value=True))
    (code, _detail, _took) = run(_door("POST", f"/tickets/{ticket}/pass", stop=False, **{"from": "ses_a", "to": "ses_b"}))
    assert code == UNCONFIRMED and ticket_index.get(ticket).holder == "ses_a"


def test_a_check_that_failed_because_the_backend_was_stopping_is_not_sent(ticket_env, monkeypatch):
    ticket = outside_ticket()
    monkeypatch.setattr(ticket_pass, "tab_reachable", AsyncMock(return_value=True))

    async def check(tab_id, text):
        stop_signal.end_work()
        raise refusal(503, "agent_message_check_failed")

    monkeypatch.setattr(ticket_pass, "check", check)
    (code, _detail, _took) = run(_door("POST", f"/tickets/{ticket}/pass", stop=False, **{"from": "ses_a", "to": "ses_b"}))
    assert code == NOT_SENT


def test_a_check_that_failed_while_the_backend_runs_keeps_its_own_code(ticket_env, monkeypatch):
    ticket = outside_ticket()
    monkeypatch.setattr(ticket_pass, "tab_reachable", AsyncMock(return_value=True))

    async def check(tab_id, text):
        raise refusal(503, "agent_message_check_failed")

    monkeypatch.setattr(ticket_pass, "check", check)
    (code, _detail, _took) = run(_door("POST", f"/tickets/{ticket}/pass", stop=False, **{"from": "ses_a", "to": "ses_b"}))
    assert code == (503, "agent_message_check_failed")


def test_a_refusal_of_a_door_is_not_changed_by_a_stop_that_has_nothing_to_do_with_it(ticket_env):
    ticket = outside_ticket()
    stop_signal.end_work()
    (code, _detail, _took) = run(_door("GET", f"/tickets/{ticket}x", stop=False, reader="ses_b"))
    assert code == (404, "ticket_unknown")


# --- the loops that run behind the doors end quietly at a stop ---


def test_an_answer_the_stop_cut_stays_queued_and_is_not_logged_as_an_error(delivery_env, monkeypatch, caplog):
    key = answered_ticket(delivery_env)

    async def stopped(_key):
        raise BackendStopping

    monkeypatch.setattr(answer_delivery, "_deliver_locked", stopped)
    with caplog.at_level(logging.INFO):
        run(answer_delivery.deliver(key))
    assert queued() == [key] and not [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert key not in answer_delivery._retry_after


def test_the_patrol_of_the_answers_and_the_return_loop_end_their_look_quietly_at_a_stop(ticket_env, monkeypatch, caplog):
    async def stopped(*_args):
        raise BackendStopping

    monkeypatch.setattr(answer_delivery, "patrol_once", stopped)
    monkeypatch.setattr(answer_delivery, "STARTUP_QUIET_SEC", 0.0)
    monkeypatch.setattr(ticket_return, "tick", stopped)

    async def loops():
        await asyncio.wait_for(asyncio.gather(answer_delivery.patrol_loop(0.01), ticket_return.return_loop(0.01)), 0.15)

    with caplog.at_level(logging.INFO), pytest.raises(asyncio.TimeoutError):
        run(loops())
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
