"""The watch over the other machines (`peers/peer_patrol.py`): each look is written down, and a machine that answers gets
its kept messages."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from backend.peers import outbox_store, peer_call, peer_health, peer_health_store, peer_patrol
from backend.tests.async_run import run
from backend.tests.peers.conftest import kept_entry

A = "a" * 32
OFF = {"online": False, "last_seen": "2026-11-16T09:00:00Z"}
TABS = (200, {"tabs": [{"id": "ses_far", "title": "notes", "running": True}]})


def test_a_machine_that_answers_is_ok_and_is_asked_for_its_tab_list_with_a_short_wait(home, far, monkeypatch):
    waits: list[float] = []
    real = peer_patrol.call_peer

    async def spy(name, peer, path, payload=None, timeout=240.0):
        waits.append(timeout)
        return await real(name, peer, path, payload, timeout)

    monkeypatch.setattr(peer_patrol, "call_peer", spy)
    far.default = TABS
    run(peer_patrol.tick())
    assert far.calls == [("http://peer.test" + peer_call.PEER_TABS_PATH, None)]
    assert waits == [peer_call.PEER_LIST_TIMEOUT_SEC]
    record = peer_health_store.get("home")
    assert (record["ok"], record["last_error"]) == (True, None)


def test_a_machine_that_does_not_answer_is_written_down_with_the_tailnet_and_gets_nothing(home, far, monkeypatch):
    monkeypatch.setattr(peer_health, "tailnet_peers", SimpleNamespace(peer_status=lambda address: OFF))
    far.goes_down()
    outbox_store.keep(kept_entry(A, kept_at=time.time()))
    run(peer_patrol.tick())
    record = peer_health_store.get("home")
    assert (record["ok"], record["last_error"], record["tailnet"]) == (False, "unreachable", OFF)
    assert far.relayed == []
    assert [e["id"] for e in outbox_store.pending("home")] == [A]


def test_since_moves_when_a_machine_goes_down_and_comes_back(home, far, sender):
    far.default = TABS
    run(peer_patrol.tick())
    up = peer_health_store.get("home")["since"]
    run(peer_patrol.tick())
    assert peer_health_store.get("home")["since"] == up
    far.goes_down()
    run(peer_patrol.tick())
    down = peer_health_store.get("home")
    assert down["ok"] is False and down["since"] >= up
    far.default = TABS
    run(peer_patrol.tick())
    back = peer_health_store.get("home")
    assert back["ok"] is True and back["since"] >= down["since"]


def test_the_look_that_finds_a_machine_back_sends_what_was_kept_for_it(home, far, sender):
    outbox_store.keep(kept_entry(A, text="while you slept", kept_at=time.time()))
    far.script = [TABS]                                   # the look; then the message gets the default (taken)
    run(peer_patrol.tick())
    assert [payload["text"] for payload in far.relayed] == ["while you slept"]
    assert outbox_store.pending() == [] and len(sender) == 1


def test_a_machine_that_is_up_but_refuses_us_is_not_ok(home, far):
    far.default = (403, {"detail": {"code": "agent_message_unknown_peer"}})
    outbox_store.keep(kept_entry(A, kept_at=time.time()))
    run(peer_patrol.tick())
    record = peer_health_store.get("home")
    assert (record["ok"], record["last_error"]) == (False, "http_403")
    assert far.relayed == []


def test_each_look_drops_the_kept_messages_that_waited_too_long(home, far, sender):
    far.goes_down()
    outbox_store.keep(kept_entry(A, kept_at=1.0))        # kept in 1970
    run(peer_patrol.tick())
    assert outbox_store.pending() == [] and 'event="expired"' in sender[0][1]


def test_with_no_machine_configured_the_watch_calls_nobody(far, sender, isolated_state):
    run(peer_patrol.tick())
    assert far.calls == []


def test_a_look_that_fails_does_not_end_the_loop(home, monkeypatch):
    looks: list[int] = []

    async def failing():
        looks.append(1)
        if len(looks) == 1:
            raise RuntimeError("boom")

    async def fast_sleep(seconds):
        if len(looks) >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(peer_patrol, "tick", failing)
    monkeypatch.setattr(peer_patrol.asyncio, "sleep", fast_sleep)
    with pytest.raises(KeyboardInterrupt):
        run(peer_patrol.peer_loop(1.0))
    assert len(looks) == 2


@pytest.mark.parametrize("value, seconds", [("2", 2.0), ("0.5", 0.5), ("soon", peer_patrol.CHECK_INTERVAL_SEC), (None, 300.0)])
def test_the_interval_is_five_minutes_unless_a_test_shortens_it(monkeypatch, value, seconds):
    if value is None:
        monkeypatch.delenv("CPC_PEER_CHECK_INTERVAL_SEC", raising=False)
    else:
        monkeypatch.setenv("CPC_PEER_CHECK_INTERVAL_SEC", value)
    assert peer_patrol._interval_sec() == seconds
