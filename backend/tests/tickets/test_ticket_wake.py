"""Waking the screens: from the loop, from another thread, with nobody connected, and the other machine's count."""
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from backend.peers.peer_call import PeerReply
from backend.tests.async_run import run
from backend.tests.tickets.samples import ticket_env  # noqa: F401
from backend.tickets import ticket_peer_count, ticket_service, ticket_wake


@pytest.fixture(autouse=True)
def _clean():
    ticket_wake._events.clear()
    ticket_peer_count._counts.clear()
    yield
    ticket_wake._events.clear()
    ticket_peer_count._counts.clear()


def test_a_change_made_in_another_thread_sets_the_event_of_a_connected_screen():
    async def scenario() -> bool:
        event = ticket_wake.subscribe()
        threading.Thread(target=ticket_wake.wake).start()
        await asyncio.wait_for(event.wait(), timeout=2.0)
        return event.is_set()

    assert run(scenario())


def test_waking_with_nobody_connected_does_nothing():
    ticket_wake.wake()


def test_an_unsubscribed_event_is_not_set():
    async def scenario() -> bool:
        event = ticket_wake.subscribe()
        ticket_wake.unsubscribe(event)
        ticket_wake.wake()
        await asyncio.sleep(0.01)
        return event.is_set()

    assert run(scenario()) is False


def test_opening_adding_asking_and_recording_each_wake_the_screens(ticket_env):
    async def scenario() -> int:
        event = ticket_wake.subscribe()
        woken = 0
        ticket = (await ticket_service.open_ticket("ses_a", "T", "R", operator_said=False))["id"]
        for step in (lambda: ticket_service.add("ses_b", ticket, "x"),
                     lambda: ticket_service.ask("ses_a", ticket, "report", "done", None)):
            await asyncio.sleep(0.01)
            woken += event.is_set()
            event.clear()
            await step()
        await asyncio.sleep(0.01)
        return woken + event.is_set()

    assert run(scenario()) == 3


def test_the_count_of_each_machine_is_read_and_a_change_wakes_the_screens(monkeypatch):
    answers = {"company": PeerReply(200, {"tickets": [{"status": "waiting-operator"}]}, True)}

    async def call_peer(name, peer, path, payload=None, timeout=0):
        return answers[name]

    monkeypatch.setattr(ticket_peer_count, "call_peer", call_peer)
    monkeypatch.setattr(ticket_peer_count._config, "AGENT_MESSAGE_PEERS", {"company": {"url": "x"}})

    async def scenario():
        event = ticket_wake.subscribe()
        await ticket_peer_count.look_once()
        await asyncio.sleep(0.01)
        first = (ticket_peer_count.counts(), event.is_set())
        event.clear()
        await ticket_peer_count.look_once()            # nothing changed: nobody is woken
        await asyncio.sleep(0.01)
        second = event.is_set()
        answers["company"] = PeerReply(None)           # the machine stops answering
        await ticket_peer_count.look_once()
        await asyncio.sleep(0.01)
        return first, second, ticket_peer_count.counts(), event.is_set()

    first, second, third, woke = run(scenario())
    assert first == ({"company": {"waiting": 1}}, True)
    assert second is False
    assert third == {"company": {"unreadable": True}} and woke is True


def test_a_machine_that_is_no_longer_configured_is_not_counted(monkeypatch):
    ticket_peer_count._counts["gone"] = 3
    monkeypatch.setattr(ticket_peer_count._config, "AGENT_MESSAGE_PEERS", {})
    assert ticket_peer_count.counts() == {}
