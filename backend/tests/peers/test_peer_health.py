"""The record of whether a machine answers: how it moves, what is read from the tailnet, and the words for the sender
(`peers/peer_health_judgement.py`, `peer_health.py`, `peer_health_store.py`)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.peers import peer_health, peer_health_store
from backend.peers.peer_call import PeerReply
from backend.peers.peer_health_judgement import (
    PEER_OFFLINE, PEER_UNREACHABLE, error_code, next_record, reason_of, unreachable_message,
)
from backend.tests.async_run import run

T0 = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
OFF = {"online": False, "last_seen": "2026-11-16T09:00:00Z"}
UNKNOWN = {"online": None, "last_seen": None}


def look(previous, *, ok, minutes, tailnet=UNKNOWN, error=None):
    return next_record(previous, ok=ok, error=error, tailnet=tailnet, now=T0 + timedelta(minutes=minutes))


# --- the record ---------------------------------------------------------------------------------


def test_since_is_when_the_machine_came_to_be_as_it_is_now():
    first = look(None, ok=True, minutes=0)
    assert first == {"ok": True, "since": "2026-11-16T12:00:00+00:00", "checked_at": "2026-11-16T12:00:00+00:00",
                     "last_error": None, "tailnet": UNKNOWN}
    still = look(first, ok=True, minutes=5)
    assert (still["since"], still["checked_at"]) == ("2026-11-16T12:00:00+00:00", "2026-11-16T12:05:00+00:00")
    down = look(still, ok=False, minutes=10, tailnet=OFF, error="unreachable")
    assert down["since"] == "2026-11-16T12:10:00+00:00" and down["tailnet"] == OFF and down["last_error"] == "unreachable"
    assert look(down, ok=False, minutes=15, tailnet=OFF, error="unreachable")["since"] == down["since"]
    assert look(down, ok=True, minutes=20)["since"] == "2026-11-16T12:20:00+00:00"


# --- the words for the sender ---------------------------------------------------------------------


def test_a_machine_off_the_tailnet_is_offline_and_says_when_it_was_last_seen():
    record = look(None, ok=False, minutes=0, tailnet=OFF)
    assert (reason_of(record), error_code(record)) == (PEER_OFFLINE, "agent_message_peer_offline")
    text = unreachable_message("home", record, T0)
    assert text.startswith("home の機械は tailnet に出ていません。 最後に見えたのは ")
    assert "(3 時間前)" in text and text.endswith("眠っているか、 電源か網が落ちています")


def test_a_machine_last_seen_a_few_minutes_ago_is_told_in_minutes():
    record = look(None, ok=False, minutes=0, tailnet={"online": False, "last_seen": "2026-11-16T11:50:00+00:00"})
    assert "(10 分前)" in unreachable_message("home", record, T0)


def test_a_machine_with_no_known_last_seen_time_says_so():
    record = look(None, ok=False, minutes=0, tailnet={"online": False, "last_seen": None})
    assert "最後に見えた時刻は分かりません" in unreachable_message("home", record, T0)


def test_a_machine_on_the_tailnet_that_does_not_answer_has_no_backend_running():
    record = look(None, ok=False, minutes=0, tailnet={"online": True, "last_seen": "2026-11-16T11:59:00Z"})
    assert (reason_of(record), error_code(record)) == (PEER_UNREACHABLE, "agent_message_peer_unreachable")
    assert unreachable_message("home", record, T0) == "home の機械は tailnet には出ていますが、 client の backend が答えません"


@pytest.mark.parametrize("record", [None, look(None, ok=False, minutes=0, tailnet=UNKNOWN)])
def test_a_machine_the_tailnet_cannot_tell_about_keeps_the_plain_words(record):
    assert reason_of(record) == PEER_UNREACHABLE
    assert unreachable_message("home", record, T0) == "home の機械に繋がりませんでした"


# --- writing it down ---------------------------------------------------------------------------


@pytest.fixture
def tailnet(monkeypatch):
    """What the tailnet says, and the addresses it was asked about."""
    asked: list[str] = []
    answer = SimpleNamespace(says=dict(UNKNOWN), asked=asked)

    def peer_status(address):
        asked.append(address)
        return answer.says

    monkeypatch.setattr(peer_health, "tailnet_peers", SimpleNamespace(peer_status=peer_status))
    return answer


PEER = {"url": "http://peer.test", "address": "100.64.0.2"}


def test_a_machine_that_answers_is_written_down_without_asking_the_tailnet(tailnet):
    record = run(peer_health.record_reply("home", PEER, PeerReply(200, {"tabs": []}, connected=True)))
    assert record["ok"] is True and record["last_error"] is None and record["tailnet"] == UNKNOWN
    assert tailnet.asked == []
    assert peer_health_store.get("home") == record


@pytest.mark.parametrize("reply, error", [
    (PeerReply(None, connected=False), "unreachable"),
    (PeerReply(None, connected=True), "no_answer"),
    (PeerReply(403, {}, connected=True), "http_403"),
])
def test_a_machine_that_does_not_answer_is_written_down_with_what_the_tailnet_says(tailnet, reply, error):
    tailnet.says = OFF
    record = run(peer_health.record_reply("home", PEER, reply))
    assert (record["ok"], record["last_error"], record["tailnet"]) == (False, error, OFF)
    assert tailnet.asked == ["100.64.0.2"]


def test_the_records_of_several_machines_share_one_file(tailnet):
    run(peer_health.record_reply("home", PEER, PeerReply(200, {}, connected=True)))
    run(peer_health.record_reply("lab", PEER, PeerReply(None)))
    file = json.loads(peer_health_store.PEER_HEALTH_PATH.read_text())
    assert {name: record["ok"] for name, record in file.items()} == {"home": True, "lab": False}


def test_a_record_that_cannot_be_read_is_started_again(tailnet):
    peer_health_store.PEER_HEALTH_PATH.write_text("{not json")
    assert peer_health_store.get("home") is None
    assert run(peer_health.record_reply("home", PEER, PeerReply(200, {}, connected=True)))["ok"] is True
