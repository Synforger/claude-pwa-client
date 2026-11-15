"""Handing a message to another machine, or keeping it when that machine does not answer (`peers/peer_send.py`)."""
from __future__ import annotations

import asyncio
import json
import urllib.error
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.peers import outbox_store, peer_health, peer_health_store, peer_send
from backend.tests.async_run import run
from backend.tests.peers.conftest import kept_entry

DOWN = urllib.error.URLError(ConnectionRefusedError("refused"))
OFF = {"online": False, "last_seen": "2026-11-16T09:00:00Z"}


def send(home, **fields):
    args = {"tab": "notes", "sender": "ses_sender", "title": "tools", "text": "hello", **fields}
    return run(peer_send.send("home", home, **args))


def tailnet_says(monkeypatch, says: dict) -> None:
    monkeypatch.setattr(peer_health, "tailnet_peers", SimpleNamespace(peer_status=lambda address: says))


def test_a_message_the_machine_takes_is_not_kept(home, far):
    answer = send(home)
    assert answer == {"ok": True, "delivered": True, "to": "home:ses_far", "operator_said": False}
    assert outbox_store.pending() == []
    assert peer_health_store.get("home")["ok"] is True


def test_a_message_carries_an_id_the_machine_can_remember(home, far):
    send(home)
    send(home)
    first, second = far.relayed
    assert len(first["message_id"]) == 32 and first["message_id"] != second["message_id"]


@pytest.mark.parametrize("says, reason", [
    (OFF, "peer_offline"),
    ({"online": True, "last_seen": "2026-11-16T12:00:00Z"}, "peer_unreachable"),
    ({"online": None, "last_seen": None}, "peer_unreachable"),
])
def test_a_machine_that_cannot_be_reached_keeps_the_message_and_says_why(home, far, monkeypatch, says, reason):
    tailnet_says(monkeypatch, says)
    far.goes_down()
    answer = send(home, text="while you sleep")
    assert (answer["ok"], answer["outbox"], answer["to"], answer["reason"]) == (True, True, "home:notes", reason)
    assert "kept" not in answer and answer["operator_said"] is False
    assert answer["peer_state"]["ok"] is False and answer["peer_state"]["tailnet"] == says
    [entry] = outbox_store.pending("home")
    assert (entry["to"], entry["from_session"], entry["from_title"], entry["text"], entry["tries"]) == (
        "notes", "ses_sender", "tools", "while you sleep", 0)
    assert entry["maybe_delivered"] is False and isinstance(entry["kept_at"], float)


def test_the_answer_says_in_words_that_the_machine_is_off_the_tailnet(home, far, monkeypatch):
    tailnet_says(monkeypatch, OFF)
    far.goes_down()
    message = send(home)["message"]
    assert message.startswith("home の機械は tailnet に出ていません。 最後に見えたのは ")
    assert message.endswith("眠っているか、 電源か網が落ちています")


def test_a_message_that_got_no_answer_after_it_was_sent_is_kept_with_the_same_id_for_the_next_send(home, far):
    """The machine may have taken it and only the answer was lost: it is kept, and sent again with the id it first had, so
    that the machine can tell."""
    far.script = [TimeoutError("timed out")]
    send(home)
    [entry] = outbox_store.pending("home")
    assert entry["maybe_delivered"] is True
    assert entry["id"] == far.relayed[0]["message_id"]


@pytest.mark.parametrize("status, code", [
    (403, "agent_message_refused"), (404, "agent_message_unknown_receiver"), (409, "agent_message_receiver_not_running"),
    (503, "agent_message_check_failed"),
])
def test_a_machine_that_answers_and_refuses_gets_its_refusal_back_and_nothing_is_kept(home, far, status, code):
    far.script = [(status, {"detail": {"code": code, "message": "the words", "params": {"status_code": status, "to": "x"}}})]
    with pytest.raises(HTTPException) as refusal:
        send(home)
    assert refusal.value.status_code == status and refusal.value.detail["code"] == code
    assert refusal.value.detail["params"] == {"to": "x", "peer": "home"}
    assert outbox_store.pending() == []


def test_a_message_that_cannot_be_kept_fails_with_the_code_of_the_reason(home, far, monkeypatch):
    tailnet_says(monkeypatch, OFF)
    far.goes_down()

    def full(entry):
        raise OSError("disk full")

    monkeypatch.setattr(outbox_store, "keep", full)
    with pytest.raises(HTTPException) as failed:
        send(home)
    assert failed.value.status_code == 502 and failed.value.detail["code"] == "agent_message_peer_offline"
    assert "tailnet に出ていません" in failed.value.detail["message"]


# --- behind earlier messages ---------------------------------------------------------------------


def test_a_message_for_a_machine_with_messages_kept_waits_behind_them_without_a_call(home, far):
    far.goes_down()
    send(home, text="first")
    calls = len(far.calls)
    answer = send(home, text="second")
    assert answer["outbox"] is True and answer["reason"] == "peer_unreachable"
    assert len(far.calls) == calls                       # the machine is known to be down: no call is made for it
    assert [e["text"] for e in outbox_store.pending("home")] == ["first", "second"]


def test_a_message_behind_earlier_ones_goes_out_after_them_when_the_machine_is_back(home, far, sender):
    far.goes_down()
    send(home, text="first")
    far.comes_back()
    peer_health_store.update("home", lambda previous: {**previous, "ok": True})   # the watch saw it come back

    async def scenario() -> dict:
        answer = await peer_send.send("home", home, tab="notes", sender="ses_sender", title="tools", text="second")
        await asyncio.gather(*peer_send._flushes)
        return answer

    answer = run(scenario())
    assert (answer["outbox"], answer["reason"]) == (True, "earlier_waiting")
    assert "先に預かった連絡" in answer["message"]
    assert [payload["text"] for payload in far.relayed[1:]] == ["first", "second"]   # [0] was the first, failed, try
    assert outbox_store.pending() == []


def test_a_new_message_does_not_overtake_one_kept_earlier(home, far, sender):
    """The machine answers again before the watch has seen it: the earlier message still goes first."""
    far.goes_down()
    send(home, text="first")
    far.comes_back()
    send(home, text="second")                             # health still says down: it is kept behind the first
    assert far.relayed[1:] == []
    from backend.peers import outbox_flush
    run(outbox_flush.flush_peer("home"))
    assert [payload["text"] for payload in far.relayed[1:]] == ["first", "second"]


def test_kept_messages_of_another_machine_do_not_hold_this_one_back(home, far):
    outbox_store.keep({**kept_entry("a" * 32), "peer": "lab"})
    assert send(home)["delivered"] is True


def test_the_record_of_a_machine_that_failed_a_send_is_updated_at_once(home, far):
    far.goes_down()
    send(home)
    record = json.loads(peer_health_store.PEER_HEALTH_PATH.read_text())["home"]
    assert (record["ok"], record["last_error"]) == (False, "unreachable")
