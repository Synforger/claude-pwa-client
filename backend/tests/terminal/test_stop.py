"""A stop of the backend ends the waits that a delivery makes in the terminal's modules (`terminal/receipt.py`,
`input_ready.py`, `confirm.py`, `first_message.py`): the responses that wait get 3 seconds when the process stops, and
these wait for seconds and minutes. What each wait leaves behind is what the sender is told: nothing typed
(`StoppedBeforeTyping`, False from the waits that only say the pane is not ready) or a text that may have arrived
(`BackendStopping`)."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from backend._internal import stop_signal
from backend.terminal import confirm, first_message as fm, input_ready, receipt
from backend.tests import async_run
from backend.tests.terminal import test_first_message_once as launch
from backend.tests.terminal.test_first_message_once import ASK, SID, pane  # noqa: F401  (= the fixture of the launch)

STOP_AFTER_SEC = 0.05
ENDS_WITHIN_SEC = 1.0


@pytest.fixture(autouse=True)
def running(monkeypatch):
    """The backend runs when a test begins, and again for the tests after it."""
    monkeypatch.setattr(stop_signal, "_stopping", False)
    input_ready._events.clear()
    yield
    input_ready._events.clear()
    input_ready.forget(SID)


def _stop_soon() -> None:
    asyncio.get_running_loop().call_later(STOP_AFTER_SEC, stop_signal.end_work)


def _timed(coroutine):
    """The result (or the exception) of `coroutine` and how long it took; a test fails when it took as long as a wait."""
    async def scenario():
        began = time.monotonic()
        try:
            return await asyncio.wait_for(coroutine, 5), time.monotonic() - began
        except Exception as error:  # noqa: BLE001 (= the test reads what ended the wait)
            return error, time.monotonic() - began
    outcome, seconds = async_run.run(scenario())
    assert seconds < ENDS_WITHIN_SEC, "the wait went on to its end"
    return outcome


# --- input_ready: the wait for a claude's startup --------------------------------------------------------------------


def test_a_stop_ends_the_wait_for_a_claude_to_report_startup_without_raising_the_flag():
    async def scenario():
        input_ready.mark_starting(SID)
        _stop_soon()
        return await input_ready.wait_ready(SID, timeout=30)
    assert _timed(scenario()) is False
    assert input_ready.is_ready(SID) is False


def test_a_wait_for_startup_that_begins_while_the_backend_stops_does_not_wait():
    async def scenario():
        input_ready.mark_starting(SID)
        stop_signal.end_work()
        return await input_ready.wait_ready(SID, timeout=30)
    assert _timed(scenario()) is False


def test_a_tab_that_is_ready_is_ready_while_the_backend_stops_too():
    async def scenario():
        stop_signal.end_work()
        return await input_ready.wait_ready("ses_never_seen")
    assert _timed(scenario()) is True


# --- confirm: the 4 seconds a typed text is looked for ------------------------------------------------------------------


def test_a_stop_ends_the_confirmation_of_a_text_that_was_typed_and_says_it_was_not_confirmed(monkeypatch, tmp_path):
    async def never_added(*_args, **_options):
        _stop_soon()
        await asyncio.sleep(30)
        return True
    monkeypatch.setattr(confirm, "_wait_count_added", never_added)
    record: Path = tmp_path / "record.jsonl"
    record.write_text("")
    assert _timed(confirm._confirm_after_send("sid", "hello", record, 0, False)) == {"ok": True, "confirmed": False}


# --- receipt: the waits of a delivery to a woken tab ----------------------------------------------------------------------


def test_a_stop_while_the_launch_holds_the_text_says_it_may_have_arrived_and_types_nothing_more(pane, monkeypatch):  # noqa: F811
    # The launch takes long to start: the text is the launch's, and only the record is watched for it.
    monkeypatch.setattr(launch, "BOOT_SEC", 30.0)

    async def scenario():
        _stop_soon()
        return await receipt.deliver_to_woken(SID, ASK)
    outcome = _timed(scenario())
    assert type(outcome) is stop_signal.BackendStopping       # not `StoppedBeforeTyping`: the text was typed
    assert pane.typed == []


def test_a_stop_while_a_launch_is_waited_for_before_the_typing_says_nothing_was_typed(pane):  # noqa: F811
    async def scenario():
        input_ready.mark_starting(SID)
        _stop_soon()
        return await receipt.deliver_to_woken(SID, ASK)
    outcome = _timed(scenario())
    assert type(outcome) is receipt.StoppedBeforeTyping
    assert pane.first_given is None and pane.typed == []


def test_a_stop_while_the_rescue_waits_leaves_the_input_as_it_is(monkeypatch):
    # A text typed into a claude that is up, whose row does not come: the rescue presses Enter and waits again. At the
    # stop it ends where it is: no key is pressed for the text, and nothing is typed again.
    keys: list[tuple] = []
    typed: list[str] = []

    async def pty_send(session_id, payload, key=None):
        typed.append(payload["text"])
        return {"ok": True, "confirmed": False}

    async def never_taken(*_args, **_options):
        _stop_soon()
        await asyncio.sleep(30)
        return False
    monkeypatch.setattr(receipt, "pty_send", pty_send)
    monkeypatch.setattr(receipt, "_taken", never_taken)
    monkeypatch.setattr(receipt, "tmux_send_keys", lambda *args, **options: keys.append((args, options)) or True)
    monkeypatch.setattr(receipt.input_ready, "launching", lambda session_id: False)
    monkeypatch.setattr(receipt, "pane_text", lambda session_id: "")
    outcome = _timed(receipt.deliver_to_woken(SID, ASK))
    assert type(outcome) is stop_signal.BackendStopping
    assert typed == [ASK] and keys == []


# --- first_message: the wait for a new pane --------------------------------------------------------------------------------


def test_a_stop_while_a_new_pane_is_waited_for_fails_the_launch_with_nothing_typed(pane, monkeypatch):  # noqa: F811
    async def pane_not_up(_sid, _timeout):
        _stop_soon()
        await asyncio.sleep(30)
        return True
    monkeypatch.setattr(fm, "wait_until_typeable", pane_not_up)
    outcome = _timed(fm.launch_with_first_message(SID, ASK))
    assert outcome == {"ok": False, "reason": "launch_failed"}
    assert pane.first_given is None
    assert input_ready.is_ready(SID) is True                   # the flag of the launch that never was is down again
