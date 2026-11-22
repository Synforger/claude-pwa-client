"""A stop of the backend ends the delivery of a message wherever it waits (`routes/agent_messages.py`,
`terminal/receipt.py`, `terminal/input_ready.py`): uvicorn gives the responses 3 seconds, and a message waiting for a
tab to wake or for its record to show the text waits for minutes. The sender is told what is true of the stage the stop
came in: nothing was typed (`agent_message_not_sent`, `agent_message_check_failed`: send again) or the text may have
arrived (`agent_message_unconfirmed`: check before sending again)."""
from __future__ import annotations

import asyncio
import time

import pytest

import backend.routes.agent_messages as am
from backend._internal import stop_signal
from backend.peers import peer_send
from backend.peers.seen_message_ids import ALREADY_DONE, claim
from backend.terminal import receipt
from backend.tests.routes.test_agent_messages import (  # noqa: F401  (= fixtures of the tests of the same door)
    _checker, _peers, _send, client, no_tmux, started, tabs, typed,
)

#: How long a wait runs on when nothing ends it: much longer than a stop needs, shorter than a test can wait.
RUNS_ON_SEC = 2.5
#: The stop comes this long after the wait began; the whole request must end within `ENDS_WITHIN_SEC` of it.
STOP_AFTER_SEC = 0.05
ENDS_WITHIN_SEC = 1.0
NOT_SENT = (503, "agent_message_not_sent")
MAY_HAVE_ARRIVED = (500, "agent_message_unconfirmed")


@pytest.fixture(autouse=True)
def running(monkeypatch):
    """The backend runs when a test begins, and again for the tests after it."""
    monkeypatch.setattr(stop_signal, "_stopping", False)


def _stop_soon() -> None:
    asyncio.get_running_loop().call_later(STOP_AFTER_SEC, stop_signal.end_work)


async def _runs_on(*_args, **_options) -> bool:
    """A wait that the stop comes during, and that would go on for `RUNS_ON_SEC` and then end well."""
    _stop_soon()
    await asyncio.sleep(RUNS_ON_SEC)
    return True


def _ended_by_the_stop(response, started_at: float) -> tuple[tuple[int, str], dict]:
    assert time.monotonic() - started_at < ENDS_WITHIN_SEC, "the request went on to the end of its wait"
    detail = response.json()["detail"]
    return (response.status_code, detail["code"]), detail


def _send_timed(client, **form):
    began = time.monotonic()
    return _send(client, **form), began


async def _at_once(*_args, **_options) -> bool:
    return True


@pytest.fixture
def real_receipt(monkeypatch, typed, started, no_tmux):
    """The delivery of a woken tab is `receipt.deliver_to_woken` itself, with its typing and its waits for the record
    in the test's hands: the typed texts go to `typed`, a text the typing hands to a launch is told as `launched`."""
    log = {"launched": False, "confirmed": False}

    async def pty_send(session_id, payload, idempotency_key=None, **_):
        typed.append((session_id, payload))
        return {"ok": True, "launched": log["launched"], "confirmed": log["confirmed"]}
    monkeypatch.setattr(am, "deliver_to_woken", receipt.deliver_to_woken)
    monkeypatch.setattr(receipt, "pty_send", pty_send)
    monkeypatch.setattr(receipt, "RESCUE_SEC", 0.2)
    monkeypatch.setattr(receipt, "pane_text", lambda session_id: "")
    monkeypatch.setattr(receipt, "tmux_send_keys", lambda *args, **options: True)
    monkeypatch.setattr(receipt, "wait_for_claude_screen", _at_once)
    monkeypatch.setattr(am, "wait_for_claude_screen", _at_once)
    monkeypatch.setattr(receipt.input_ready, "launching", lambda session_id: False)
    return log


# --- before anything is typed ------------------------------------------------------------------------------------------


def test_a_stop_while_the_tab_wakes_says_nothing_was_sent(client, tabs, typed, started, no_tmux, monkeypatch):
    monkeypatch.setattr(am.input_ready, "wait_ready", _runs_on)
    r, began = _send_timed(client, to="ses_idle")
    (status_and_code, detail) = _ended_by_the_stop(r, began)
    assert status_and_code == NOT_SENT
    assert detail["params"]["reason"] == "backend_stopping" and "何も届いていません" in detail["message"]
    assert typed == []


def test_a_stop_while_a_launch_is_waited_for_before_the_typing_says_nothing_was_sent(client, tabs, typed, started,
                                                                                    real_receipt, monkeypatch):
    monkeypatch.setattr(receipt.input_ready, "launching", lambda session_id: True)
    monkeypatch.setattr(receipt.input_ready, "wait_launched", _runs_on)
    r, began = _send_timed(client, to="ses_idle")
    assert _ended_by_the_stop(r, began)[0] == NOT_SENT
    assert typed == []


def test_a_stop_while_the_screen_of_a_started_claude_is_waited_for_says_nothing_was_sent(client, tabs, typed, started,
                                                                                         real_receipt, monkeypatch):
    monkeypatch.setattr(receipt.input_ready, "launching", lambda session_id: True)
    monkeypatch.setattr(receipt.input_ready, "wait_launched", _at_once)
    monkeypatch.setattr(receipt, "wait_for_claude_screen", _runs_on)
    r, began = _send_timed(client, to="ses_idle")
    assert _ended_by_the_stop(r, began)[0] == NOT_SENT
    assert typed == []


def test_a_stop_while_the_check_runs_says_the_check_did_not_run(client, tabs, typed, monkeypatch, tmp_path):
    _checker(monkeypatch, tmp_path, "import time\ntime.sleep(1.5)\n")
    original = am._run_check
    ended: list[float] = []

    async def check_then_stop(*args, **options):
        _stop_soon()
        try:
            return await original(*args, **options)
        finally:
            ended.append(time.monotonic())
    monkeypatch.setattr(am, "_run_check", check_then_stop)
    began = time.monotonic()
    r = _send(client)
    # The check's own thread runs to its end and the test client's loop waits for it when it closes, so the response
    # is only said to have come at the check's end: the wait for it ended at the stop.
    assert ended[0] - began < ENDS_WITHIN_SEC
    detail = r.json()["detail"]
    assert (r.status_code, detail["code"]) == (503, "agent_message_check_failed") and "stopping" in detail["message"]
    assert typed == []


def test_a_message_that_comes_while_the_backend_stops_sends_nothing(client, tabs, typed):
    stop_signal.end_work()
    r, began = _send_timed(client)
    assert _ended_by_the_stop(r, began)[0] == NOT_SENT
    assert typed == []


def test_a_backend_started_again_takes_messages_again(client, tabs, typed):
    stop_signal.end_work()
    stop_signal.accept_work()
    assert _send(client).status_code == 200 and len(typed) == 1


def test_the_id_of_a_message_that_was_not_sent_is_forgotten_so_that_the_next_try_delivers_it(client, tabs, typed,
                                                                                            monkeypatch):
    ident = "ab" * 16
    stop_signal.end_work()
    assert _ended_by_the_stop(*_send_timed(client, message_id=ident))[0] == NOT_SENT
    stop_signal.accept_work()
    r = _send(client, message_id=ident)
    assert r.status_code == 200 and "duplicate" not in r.json() and len(typed) == 1


# --- after the typing --------------------------------------------------------------------------------------------------


def test_a_stop_while_a_text_the_launch_holds_is_waited_for_says_it_may_have_arrived(client, tabs, typed, started,
                                                                                    real_receipt, monkeypatch):
    # the wait for the launch that holds the text: `deliver_to_woken` -> `_taken_by_launch` -> `wait_launched`
    real_receipt["launched"] = True
    calls = {"launching": 0}

    def launching(session_id):
        calls["launching"] += 1
        return calls["launching"] == 1          # in flight before the typing, not any more once it is typed
    monkeypatch.setattr(receipt.input_ready, "launching", launching)
    monkeypatch.setattr(receipt.input_ready, "wait_launched", _after_the_typing(typed))
    r, began = _send_timed(client, to="ses_idle")
    (status_and_code, detail) = _ended_by_the_stop(r, began)
    assert status_and_code == MAY_HAVE_ARRIVED
    assert detail["params"]["reason"] == "backend_stopping" and "届いているかもしれません" in detail["message"]
    assert len(typed) == 1


def _after_the_typing(typed):
    """A wait that only runs on once the text was typed (= the stop comes during it, not before)."""
    async def wait(session_id):
        assert typed, "the wait began before the text was typed"
        return await _runs_on()
    return wait


def test_a_stop_while_the_record_is_waited_for_says_it_may_have_arrived(client, tabs, typed, started, real_receipt,
                                                                       monkeypatch):
    monkeypatch.setattr(receipt, "_taken", _runs_on_false)
    r, began = _send_timed(client, to="ses_idle")
    assert _ended_by_the_stop(r, began)[0] == MAY_HAVE_ARRIVED
    assert len(typed) == 1                                       # nothing was typed again


async def _runs_on_false(*_args, **_options) -> bool:
    _stop_soon()
    await asyncio.sleep(RUNS_ON_SEC)
    return False


def test_a_stop_during_the_rescue_says_it_may_have_arrived(client, tabs, typed, started, real_receipt, monkeypatch):
    monkeypatch.setattr(receipt, "RESCUE_SEC", 60.0)
    taken = {"asked": 0}

    async def row_comes_late(*_args, **_options) -> bool:
        taken["asked"] += 1
        if taken["asked"] == 1:
            return False                                    # the first look finds nothing: the rescue begins
        return await _runs_on_false()
    monkeypatch.setattr(receipt, "_taken", row_comes_late)
    r, began = _send_timed(client, to="ses_idle")
    assert _ended_by_the_stop(r, began)[0] == MAY_HAVE_ARRIVED


def test_the_id_of_a_message_that_may_have_arrived_is_kept_so_that_a_second_send_is_not_typed(client, tabs, typed,
                                                                                            started, real_receipt,
                                                                                            monkeypatch):
    ident = "cd" * 16
    monkeypatch.setattr(receipt, "_taken", _runs_on_false)
    assert _ended_by_the_stop(*_send_timed(client, to="ses_idle", message_id=ident))[0] == MAY_HAVE_ARRIVED
    assert claim(ident) == ALREADY_DONE


def test_a_stop_while_another_machine_answers_says_the_message_may_have_arrived(client, tabs, monkeypatch, tmp_path):
    _peers(monkeypatch, tmp_path)

    async def answers_late(*_args, **_options) -> dict:
        await _runs_on()
        return {"ok": True}
    monkeypatch.setattr(peer_send, "send", answers_late)
    r, began = _send_timed(client, to="home:notes")
    assert _ended_by_the_stop(r, began)[0] == MAY_HAVE_ARRIVED
