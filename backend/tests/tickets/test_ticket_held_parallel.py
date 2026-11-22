"""`tabs ticket mine` looks at the tickets a tab holds at the same time, a few at once (`ticket_held.HELD_PARALLEL`), and gives
what it gave when it looked at them one by one: the same tickets in the same order, the same machine named as not answering."""
from __future__ import annotations

import asyncio

import pytest

from backend.tests.async_run import run
from backend.tests.tickets.samples import outside_ticket, relay_env  # noqa: F401
from backend.tests.tickets.samples import ticket_env  # noqa: F401
from backend.tickets import guard_command, ticket_held

PEERS_TICKETS = "/agent-messages/tickets"
HELD_COUNT = 6
#: How long a stand-in for the guard's command takes (= long enough for the others to start meanwhile)
COMMAND_SEC = 0.05
#: The most commands one ticket has running at once: its title and its last line are judged side by side
COMMANDS_PER_TICKET = 2


@pytest.fixture
def commands(ticket_env, monkeypatch):
    """The guard's commands judge every text and tab as allowed, take `COMMAND_SEC`, and are counted: how many ran at the same
    time at most (`peak`) and how many ran (`count`)."""
    ticket_env.guard.use("read", "covers")
    state = {"running": 0, "peak": 0, "count": 0}

    async def run_command(command, names, text=None):
        state["running"] += 1
        state["count"] += 1
        state["peak"] = max(state["peak"], state["running"])
        await asyncio.sleep(COMMAND_SEC)
        state["running"] -= 1
        return guard_command.CommandResult(0, "", "")

    monkeypatch.setattr(guard_command, "run_command", run_command)
    return state


def _hold_many(count: int = HELD_COUNT) -> list[str]:
    return [outside_ticket(title=f"Ticket {number}", holder="ses_a") for number in range(count)]


def test_the_tickets_are_looked_at_together_and_not_more_than_the_limit_at_once(commands):
    _hold_many()
    asked_at_once = ticket_held.HELD_PARALLEL
    run(ticket_held.held_by("ses_a", None))
    assert commands["peak"] > 1
    assert commands["peak"] <= asked_at_once * COMMANDS_PER_TICKET


def test_what_is_given_is_what_looking_at_them_one_by_one_gives(commands, monkeypatch):
    _hold_many()
    together = run(ticket_held.held_by("ses_a", None))
    monkeypatch.setattr(ticket_held, "HELD_PARALLEL", 1)
    one_by_one = run(ticket_held.held_by("ses_a", None))
    assert together == one_by_one and [ticket["title"] for ticket in together["tickets"]] == [f"Ticket {n}" for n in range(HELD_COUNT)]


def test_the_other_machines_tickets_come_after_this_ones_in_the_order_it_listed_them(relay_env, commands, monkeypatch):
    relay_env.configure("company", "home")
    _hold_many(3)
    remote = [f"home-261119-0{number}" for number in range(1, 5)]
    relay_env.peer_says[PEERS_TICKETS] = (200, {"ok": True, "tickets": [
        {"id": ticket, "status": "open", "holder": "ses_a", "opener": "ses_b", "origin": "tab", "due": None} for ticket in remote]})
    for ticket in remote:
        relay_env.peer_says[f"/agent-messages/tickets/{ticket}"] = (200, {"ok": True, "entries": [
            {"kind": "opened", "title": f"Remote {ticket}", "at": "2026-11-19T00:00:00.000Z", "text": "r"}]})
    together = run(ticket_held.held_by("ses_a", None))
    monkeypatch.setattr(ticket_held, "HELD_PARALLEL", 1)
    one_by_one = run(ticket_held.held_by("ses_a", None))
    assert together == one_by_one
    assert [ticket["id"] for ticket in together["tickets"]][3:] == remote


def test_a_machine_that_does_not_answer_is_named_and_the_rest_is_given(relay_env, commands):
    relay_env.configure("company", "home")
    _hold_many(2)
    relay_env.peer_says[PEERS_TICKETS] = relay_env.down
    answer = run(ticket_held.held_by("ses_a", None))
    assert len(answer["tickets"]) == 2 and answer["peer_unreachable"] == ["home"]
