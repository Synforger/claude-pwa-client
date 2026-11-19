"""The queue of answers: one entry for each `(ticket id, asked_at)`, kept in a file, with no words in it."""
from __future__ import annotations

import json

from backend.tests.tickets.samples import ticket_env  # noqa: F401
from backend.tickets import answer_queue
from backend.tickets.answer_queue import AnswerKey

FIRST, SECOND = AnswerKey("home-261119-01", "2026-11-19T01:00:00.000+00:00"), AnswerKey("home-261119-01", "2026-11-19T02:00:00.000+00:00")


def test_a_key_is_added_once_and_the_queue_keeps_the_order(ticket_env):
    assert answer_queue.add(FIRST) and answer_queue.add(SECOND)
    assert not answer_queue.add(FIRST)
    assert answer_queue.keys() == [FIRST, SECOND]


def test_the_same_ticket_with_another_asked_line_is_another_key(ticket_env):
    answer_queue.add(FIRST)
    assert not answer_queue.contains(SECOND)
    assert answer_queue.pending_for("home-261119-01") and not answer_queue.pending_for("home-261119-02")


def test_a_key_is_taken_out_and_a_key_that_is_not_there_is_left_alone(ticket_env):
    answer_queue.add(FIRST)
    answer_queue.remove(SECOND)
    answer_queue.remove(FIRST)
    assert answer_queue.keys() == []


def test_the_file_holds_only_the_keys(ticket_env):
    answer_queue.add(FIRST)
    assert json.loads((ticket_env.tickets / "answer-queue.json").read_text()) == [
        {"ticket": FIRST.ticket, "asked_at": FIRST.asked_at}]


def test_a_missing_or_damaged_file_is_an_empty_queue(ticket_env):
    assert answer_queue.keys() == []
    ticket_env.tickets.mkdir(parents=True)
    (ticket_env.tickets / "answer-queue.json").write_text("{not json")
    assert answer_queue.keys() == []
    (ticket_env.tickets / "answer-queue.json").write_text('[{"ticket": 1}, "x", {"ticket": "a", "asked_at": "b"}]')
    assert answer_queue.keys() == [AnswerKey("a", "b")]
