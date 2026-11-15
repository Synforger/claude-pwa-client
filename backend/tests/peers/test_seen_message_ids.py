"""The ids of the messages this machine took (`peers/seen_message_ids.py`): a message delivered once is not typed twice."""
from __future__ import annotations

import json
import time

import pytest
from fastapi import HTTPException

from backend.peers import seen_message_ids as seen
from backend.peers.seen_message_ids import ALREADY_DONE, CLAIMED, STILL_IN_FLIGHT, claim, complete, release

HOUR = 3600
ID = "a" * 32


def table() -> dict:
    return json.loads(seen.SEEN_MESSAGE_IDS_PATH.read_text())


def test_an_id_is_in_flight_from_the_claim_and_done_once_completed():
    assert claim(ID, now=0) == CLAIMED
    assert table()[ID]["state"] == "in_flight"
    assert claim(ID, now=1) == STILL_IN_FLIGHT
    complete(ID, now=2)
    assert table()[ID] == {"state": "done", "at": 2}
    assert claim(ID, now=3) == ALREADY_DONE


def test_an_id_that_failed_is_forgotten_so_that_a_later_send_delivers_it():
    claim(ID, now=0)
    release(ID)
    assert ID not in table()
    assert claim(ID, now=1) == CLAIMED


def test_an_id_is_remembered_for_96_hours_and_forgotten_after():
    claim(ID, now=0)
    complete(ID, now=0)
    assert claim(ID, now=96 * HOUR) == ALREADY_DONE          # the edge still counts
    assert claim(ID, now=96 * HOUR + 1) == CLAIMED           # one second later it is a new message
    assert table()[ID]["state"] == "in_flight"


def test_old_ids_are_dropped_from_the_file_when_it_is_written():
    complete("b" * 32, now=0)
    complete("c" * 32, now=97 * HOUR)
    assert list(table()) == ["c" * 32]


def test_ids_in_flight_are_forgotten_at_the_start_and_done_ones_stay():
    now = time.time()
    claim(ID, now=now)
    complete("d" * 32, now=now)
    claim("e" * 32, now=now)
    seen.forget_in_flight()
    assert list(table()) == ["d" * 32]


def test_a_file_that_cannot_be_read_is_started_again():
    seen.SEEN_MESSAGE_IDS_PATH.write_text("[1, 2")
    assert claim(ID, now=0) == CLAIMED


# --- around a delivery ----------------------------------------------------------------------------


def test_a_message_with_no_id_is_always_delivered():
    for _ in range(2):
        with seen.delivering(None) as first:
            assert first is True
    assert not seen.SEEN_MESSAGE_IDS_PATH.exists()


def test_the_second_delivery_of_an_id_is_not_made():
    with seen.delivering(ID) as first:
        assert first is True
    with seen.delivering(ID) as again:
        assert again is False
    assert table()[ID]["state"] == "done"


def test_an_id_still_being_delivered_is_refused_with_409():
    with seen.delivering(ID):
        with pytest.raises(HTTPException) as refused:
            with seen.delivering(ID):
                raise AssertionError("must not deliver while the first delivery runs")
    assert refused.value.status_code == 409 and refused.value.detail["code"] == "agent_message_in_flight"


def test_a_delivery_that_raises_forgets_the_id():
    with pytest.raises(RuntimeError):
        with seen.delivering(ID):
            raise RuntimeError("the tab did not take it")
    assert ID not in table()
    with seen.delivering(ID) as first:
        assert first is True
