"""What a kept message comes to, given the other machine's answer (`peers/outbox_judgement.py`), and its notices
(`peers/outbox_notice.py`)."""
from __future__ import annotations

import pytest

from backend.jsonl.jsonl_predicates import CLIENT_NOTICE_OPENING
from backend.peers import outbox_judgement as judgement, outbox_notice as notice
from backend.peers.peer_call import PeerReply
from backend.tests.peers.conftest import kept_entry

HOUR = 3600


@pytest.mark.parametrize("reply, verdict", [
    (PeerReply(200, {"ok": True}, True), judgement.DELIVERED),
    (PeerReply(400, {}, True), judgement.REFUSED),
    (PeerReply(403, {}, True), judgement.REFUSED),
    (PeerReply(404, {}, True), judgement.REFUSED),
    (PeerReply(409, {}, True), judgement.TRY_LATER),      # not ready, or the same message is in flight
    (PeerReply(500, {}, True), judgement.TRY_LATER),
    (PeerReply(503, {}, True), judgement.TRY_LATER),
    (PeerReply(422, {}, True), judgement.TRY_LATER),      # only 400, 403 and 404 are final
    (PeerReply(None, connected=False), judgement.NOT_REACHED),
    (PeerReply(None, connected=True), judgement.NOT_REACHED),
])
def test_only_400_403_404_end_a_kept_message(reply, verdict):
    assert judgement.verdict(reply) == verdict


def test_a_message_expires_after_72_hours():
    entry = kept_entry("a" * 32, kept_at=1_000)
    assert judgement.EXPIRY_SEC == 72 * HOUR
    assert not judgement.is_expired(entry, 1_000 + 72 * HOUR)
    assert judgement.is_expired(entry, 1_000 + 72 * HOUR + 1)


def test_a_refusal_gives_its_code_and_words():
    reply = PeerReply(403, {"detail": {"code": "agent_message_refused", "message": "no"}}, True)
    assert judgement.refusal_of(reply) == ("agent_message_refused", "no")
    assert judgement.refusal_of(PeerReply(400, {}, True)) == ("http_400", "HTTP 400")


def test_the_notices_are_the_client_s_own_and_name_the_message():
    entry = kept_entry("a" * 32, to="notes")
    delivered = notice.notice_envelope(notice.DELIVERED, entry)
    assert delivered.startswith(CLIENT_NOTICE_OPENING + "\n") and '<peer-outbox event="delivered" to="home:notes">' in delivered
    assert "has arrived" in delivered and "home:notes" in delivered
    expired = notice.notice_envelope(notice.EXPIRED, entry)
    assert "72 hours" in expired and "dropped" in expired
    refused = notice.notice_envelope(notice.REFUSED, entry, "the text was refused", "agent_message_refused")
    assert 'code="agent_message_refused"' in refused and "the text was refused" in refused


def test_a_message_to_a_tab_that_is_gone_says_so():
    refused = notice.notice_envelope(notice.REFUSED, kept_entry("a" * 32), "宛先のタブが見つかりません", judgement.UNKNOWN_RECEIVER)
    assert "no such tab on that machine (it was renamed or closed)" in refused


def test_a_name_cannot_break_out_of_the_notice():
    entry = {**kept_entry("a" * 32), "peer": "home", "to": 'x">\n</peer-outbox>'}
    assert notice.notice_envelope(notice.DELIVERED, entry).count("</peer-outbox>") == 1
