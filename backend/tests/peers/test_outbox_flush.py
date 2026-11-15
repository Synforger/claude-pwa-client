"""Sending the kept messages again once the machine answers, and dropping those that waited too long
(`peers/outbox_flush.py`)."""
from __future__ import annotations

import asyncio
import json
import urllib.error

import pytest

import backend._common.config as config_mod
from backend.peers import outbox_flush, outbox_store, peer_health_store
from backend.peers.outbox_flush import expire_old, flush_peer
from backend.tests.async_run import run
from backend.tests.peers.conftest import kept_entry

HOUR = 3600
A, B, C = "a" * 32, "b" * 32, "c" * 32
DOWN = urllib.error.URLError(ConnectionRefusedError("refused"))
REFUSAL = {"detail": {"code": "agent_message_refused", "message": "carries text the receiver has not read"}}


def keep(*entries: dict) -> None:
    for entry in entries:
        outbox_store.keep(entry)


def kept_ids() -> list[str]:
    return [entry["id"] for entry in outbox_store.pending("home")]


def test_the_kept_messages_go_oldest_first_and_each_is_deleted_when_it_arrives(home, far, sender):
    keep(kept_entry(B, kept_at=2_000, text="second"), kept_entry(A, kept_at=1_000, text="first"))
    run(flush_peer("home"))
    assert [(payload["message_id"], payload["text"]) for payload in far.relayed] == [(A, "first"), (B, "second")]
    assert far.relayed[0] == {"to": "notes", "from_title": "tools", "from_session": "ses_sender", "text": "first",
                              "message_id": A}
    assert kept_ids() == []


def test_the_sender_is_told_for_each_message_that_arrived(home, far, sender):
    keep(kept_entry(A, kept_at=1_000), kept_entry(B, kept_at=2_000, to="plans"))
    run(flush_peer("home"))
    assert [tab for tab, _ in sender] == ["ses_sender", "ses_sender"]
    first, second = (text for _, text in sender)
    assert 'event="delivered" to="home:notes"' in first and 'event="delivered" to="home:plans"' in second
    assert first.startswith("Sent by the client (the operator did not type this):")


def test_a_message_the_other_machine_already_has_is_taken_as_arrived(home, far, sender):
    far.default = (200, {"ok": True, "duplicate": True})
    keep(kept_entry(A))
    run(flush_peer("home"))
    assert kept_ids() == [] and len(sender) == 1 and "has arrived" in sender[0][1]


def test_a_machine_that_does_not_answer_stops_the_flush_and_keeps_the_rest(home, far, sender):
    far.script = [(200, {"ok": True}), DOWN]
    keep(kept_entry(A, kept_at=1), kept_entry(B, kept_at=2), kept_entry(C, kept_at=3))
    run(flush_peer("home"))
    assert len(far.relayed) == 2                     # C was not tried: the machine is down again
    assert kept_ids() == [B, C]
    assert outbox_store.pending("home")[0]["tries"] == 1
    assert peer_health_store.get("home")["ok"] is False
    assert len(sender) == 1                          # only A's arrival was told


@pytest.mark.parametrize("status, code", [
    (400, "agent_message_bad_relay"), (403, "agent_message_refused"), (404, "agent_message_unknown_receiver"),
])
def test_a_message_the_machine_refuses_for_good_is_deleted_and_its_sender_told(home, far, sender, status, code):
    far.script = [(status, {"detail": {"code": code, "message": "the words of the refusal"}})]
    keep(kept_entry(A, kept_at=1), kept_entry(B, kept_at=2))
    run(flush_peer("home"))
    assert kept_ids() == []                           # the refused one is gone, the next one went through
    assert len(far.relayed) == 2
    (_, notice), _arrived = sender
    assert f'event="refused" to="home:notes" code="{code}"' in notice


def test_a_message_for_a_tab_that_is_gone_says_the_tab_is_gone(home, far, sender):
    far.script = [(404, {"detail": {"code": "agent_message_unknown_receiver", "message": "宛先のタブが見つかりません"}})]
    keep(kept_entry(A))
    run(flush_peer("home"))
    assert "no such tab on that machine (it was renamed or closed)" in sender[0][1]


@pytest.mark.parametrize("status", [409, 500, 502, 503, 422])
def test_a_message_the_machine_cannot_take_now_is_kept_until_it_runs_out_of_time(home, far, sender, status):
    far.script = [(status, {"detail": {"code": "agent_message_receiver_not_ready"}})]
    keep(kept_entry(A))
    run(flush_peer("home"))
    assert kept_ids() == [A] and outbox_store.pending("home")[0]["tries"] == 1 and sender == []


def test_a_message_waiting_for_its_tab_holds_back_the_later_ones_for_that_tab_only(home, far, sender):
    """Order is kept per tab: a tab that cannot take its message yet does not take a later one first, and the messages for
    other tabs are not held up by it."""
    far.script = [(409, {"detail": {"code": "agent_message_receiver_not_running"}})]
    keep(kept_entry(A, to="notes", kept_at=1), kept_entry(B, to="notes", kept_at=2), kept_entry(C, to="plans", kept_at=3))
    run(flush_peer("home"))
    assert [payload["message_id"] for payload in far.relayed] == [A, C]
    assert kept_ids() == [A, B]


def test_a_message_the_machine_is_still_delivering_is_sent_again_on_the_next_round(home, far, sender):
    far.script = [(409, {"detail": {"code": "agent_message_in_flight"}})]
    keep(kept_entry(A))
    run(flush_peer("home"))
    assert kept_ids() == [A]
    run(flush_peer("home"))
    assert kept_ids() == [] and [payload["message_id"] for payload in far.relayed] == [A, A]


def test_a_flush_that_is_running_is_not_started_a_second_time(home, far, sender):
    keep(kept_entry(A, kept_at=1), kept_entry(B, kept_at=2))

    async def twice() -> None:
        await asyncio.gather(flush_peer("home"), flush_peer("home"))

    run(twice())
    assert [payload["message_id"] for payload in far.relayed] == [A, B]


def test_a_message_added_while_the_flush_runs_goes_out_in_the_same_flush_after_the_others(home, monkeypatch, far, sender):
    keep(kept_entry(A, kept_at=1))
    real = outbox_flush.call_peer

    async def adding(name, peer, path, payload=None, timeout=240.0):
        if payload["message_id"] == A:
            keep(kept_entry(B, kept_at=2))
        return await real(name, peer, path, payload, timeout)

    monkeypatch.setattr(outbox_flush, "call_peer", adding)
    run(flush_peer("home"))
    assert [payload["message_id"] for payload in far.relayed] == [A, B] and kept_ids() == []


def test_a_flush_that_stopped_halfway_is_taken_up_where_it_was_by_a_backend_that_started_again(home, far, sender, monkeypatch):
    far.script = [(200, {"ok": True}), DOWN]
    keep(kept_entry(A, kept_at=1), kept_entry(B, kept_at=2))
    run(flush_peer("home"))
    assert kept_ids() == [B]
    monkeypatch.setattr(outbox_flush, "_locks", {})   # the backend starts again: only the files are left
    far.comes_back()
    run(flush_peer("home"))
    assert [payload["message_id"] for payload in far.relayed] == [A, B, B] and kept_ids() == []


def test_a_machine_taken_out_of_the_settings_is_not_flushed(home, far, sender):
    keep(kept_entry(A))
    config_mod.CONFIG_PATH.write_text("{}")
    config_mod.get_config.cache_clear()
    run(flush_peer("home"))
    assert far.calls == [] and kept_ids() == [A]


def test_a_sender_whose_claude_is_not_running_is_not_woken_but_the_message_still_goes(home, far, sender, monkeypatch):
    from backend.routes import agent_messages as am
    monkeypatch.setattr(am, "_tab_running", lambda tab_id: False)
    keep(kept_entry(A))
    run(flush_peer("home"))
    assert kept_ids() == [] and sender == []


def test_a_sender_that_does_not_exist_any_more_is_not_told(home, far, sender, isolated_state):
    del isolated_state.sessions_meta["ses_sender"]
    keep(kept_entry(A))
    run(flush_peer("home"))
    assert kept_ids() == [] and sender == []


# --- the 72 hours -----------------------------------------------------------------------------------


def test_a_message_kept_longer_than_72_hours_is_dropped_and_its_sender_told(home, far, sender):
    keep(kept_entry(A, kept_at=1_000), kept_entry(B, kept_at=1_000 + 24 * HOUR))
    run(expire_old(1_000 + 72 * HOUR + 1))
    assert kept_ids() == [B]
    ((tab, notice),) = sender
    assert tab == "ses_sender" and 'event="expired" to="home:notes"' in notice and "72 hours" in notice
    assert far.calls == []


def test_a_message_at_exactly_72_hours_is_still_kept(home, far, sender):
    keep(kept_entry(A, kept_at=1_000))
    run(expire_old(1_000 + 72 * HOUR))
    assert kept_ids() == [A] and sender == []


def test_a_message_for_a_machine_no_longer_configured_is_dropped_all_the_same(home, far, sender):
    keep({**kept_entry(A, kept_at=1_000), "peer": "gone"})
    run(expire_old(1_000 + 73 * HOUR))
    assert outbox_store.pending() == [] and len(sender) == 1


def test_a_kept_message_that_cannot_be_read_is_left_alone(home, far, sender):
    keep(kept_entry(A, kept_at=1))
    (outbox_store.PEER_OUTBOX_DIR / "broken.json").write_text("{not json")
    run(flush_peer("home"))
    assert kept_ids() == [] and (outbox_store.PEER_OUTBOX_DIR / "broken.json").exists()


def test_a_message_is_one_file_named_by_its_id(home):
    keep(kept_entry(A))
    assert json.loads((outbox_store.PEER_OUTBOX_DIR / f"{A}.json").read_text())["text"] == "hello"
    outbox_store.remove(A)
    outbox_store.remove(A)                              # deleting twice is no error
    assert list(outbox_store.PEER_OUTBOX_DIR.glob("*")) == []


def test_a_notice_hands_its_sender_no_work(home, far, sender, monkeypatch):
    """A parent's child that reported is not set back to working by the client's own notice."""
    from backend.routes import agent_messages as am

    def hands_work(*args):
        raise AssertionError("a notice must not hand work")

    monkeypatch.setattr(am, "hand_work", hands_work)
    keep(kept_entry(A))
    run(flush_peer("home"))
    assert len(sender) == 1
