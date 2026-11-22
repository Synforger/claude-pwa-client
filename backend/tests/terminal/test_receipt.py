"""Getting a message into a tab whose claude was just started (`terminal/receipt.py`): the screen is waited for, and
the message is looked for in the record, with one rescue."""
from __future__ import annotations

import json

import pytest

import backend.terminal.receipt as receipt
from backend.permission_window.window_screen import read_screen
from backend.tests.async_run import run
from backend.tests.permission_window import screens

CLAUDE_SCREEN = "some history\n╭─────╮\n│ >   │\n╰─────╯\n  5h:12% ctx:3%"
LOADING = "Resuming conversation…"
TEXT = "Sent by the client (the operator did not type this):\n<account-move from=\"a\" to=\"b\" reason=\"limit\">\nCarry on.\n</account-move>"


@pytest.fixture
def pane(monkeypatch):
    """What the pane shows: a list of screens, the last one stays. Looks are quick."""
    shown = {"screens": [LOADING], "looks": 0}

    def text(_session_id):
        shown["looks"] += 1
        return shown["screens"][min(shown["looks"], len(shown["screens"])) - 1]
    monkeypatch.setattr(receipt, "pane_text", text)
    monkeypatch.setattr(receipt, "SCREEN_LOOK_SEC", 0.01)
    monkeypatch.setattr(receipt, "SCREEN_WAIT_SEC", 0.3)
    return shown


def test_a_pane_that_becomes_claudes_screen_is_waited_for(pane):
    pane["screens"] = [LOADING, LOADING, CLAUDE_SCREEN]
    assert run(receipt.wait_for_claude_screen("ses_x")) is True
    assert pane["looks"] == 3


def test_a_pane_that_never_does_is_given_up_on(pane):
    assert run(receipt.wait_for_claude_screen("ses_x")) is False


@pytest.mark.parametrize("pane_text, waits", [
    ("│ > Sent by the client (the operator did not type this):", True),     # the beginning is on the screen
    ("│ > [Pasted text #1 +4 lines]", True),                                  # a long paste the TUI did not send
    ("│ >  \n  5h:12% ctx:3%", False),                                        # an empty input
])
def test_the_pane_says_whether_the_text_waits_in_the_input(pane_text, waits):
    assert receipt.text_waits_in_input(pane_text, TEXT) is waits


@pytest.fixture
def typing(monkeypatch, pane):
    """The typing and the record: `taken` is the answers of the waits for the row, in order (the last one stays)."""
    log = {"typed": 0, "enters": 0, "keys": [], "taken": [], "asked": [], "confirmed": False}

    async def pty_send(session_id, payload, key=None, **_):
        log["typed"] += 1
        return {"ok": True, "confirmed": log["confirmed"]}

    async def taken(session_id, initial_pos, timeout, text):
        log["asked"].append(timeout)
        answers = log["taken"]
        return answers[min(len(log["asked"]), len(answers)) - 1] if answers else False

    def keys(session_id, text=None, key=None, enter=False):
        log["enters"] += 1 if enter and text is None else 0
        if key is not None:
            log["keys"].append(key)
        return True
    monkeypatch.setattr(receipt, "pty_send", pty_send)
    monkeypatch.setattr(receipt, "_taken", taken)
    monkeypatch.setattr(receipt, "tmux_send_keys", keys)
    monkeypatch.setattr(receipt, "_record_end", lambda _sid: 0)
    pane["screens"] = [CLAUDE_SCREEN]
    return log


def test_a_message_the_record_shows_is_taken_without_any_rescue(typing):
    typing["confirmed"] = True
    assert run(receipt.deliver_to_woken("ses_x", TEXT)) is True
    assert (typing["typed"], typing["enters"], typing["asked"]) == (1, 0, [])


def test_a_row_that_comes_a_little_later_is_taken_too(typing):
    typing["taken"] = [True]
    assert run(receipt.deliver_to_woken("ses_x", TEXT)) is True
    assert (typing["typed"], typing["enters"]) == (1, 0)


def test_the_wait_adds_up_to_ten_seconds_with_the_confirmation_of_the_typing(typing):
    typing["taken"] = [True]
    run(receipt.deliver_to_woken("ses_x", TEXT))
    assert typing["asked"] == [receipt.TAKEN_WAIT_SEC - receipt.CONFIRM_TIMEOUT_SEC]


def test_a_text_that_waits_in_the_input_gets_one_enter_and_not_a_second_typing(typing, pane):
    pane["screens"] = ["│ > Sent by the client (the operator did not type this):\n" + CLAUDE_SCREEN]
    typing["taken"] = [False, True]
    assert run(receipt.deliver_to_woken("ses_x", TEXT)) is True
    assert (typing["typed"], typing["enters"]) == (1, 1)


def test_a_text_that_is_gone_is_typed_once_more(typing):
    typing["taken"] = [False, True]
    assert run(receipt.deliver_to_woken("ses_x", TEXT)) is True
    assert (typing["typed"], typing["enters"]) == (2, 0)


@pytest.fixture
def short_rescue(monkeypatch):
    monkeypatch.setattr(receipt, "RESCUE_SEC", 0.05)


def test_a_text_left_in_the_input_gets_enter_again_until_it_is_taken(typing, pane):
    # A claude that has just read a long conversation on a busy machine drops the first Enters.
    pane["screens"] = ["│ > Sent by the client (the operator did not type this):\n" + CLAUDE_SCREEN]
    typing["taken"] = [False, False, False, True]
    assert run(receipt.deliver_to_woken("ses_x", TEXT)) is True
    assert (typing["typed"], typing["enters"]) == (1, 3)


def test_each_wait_after_an_enter_is_a_short_one(typing, pane):
    pane["screens"] = ["│ > Sent by the client (the operator did not type this):\n" + CLAUDE_SCREEN]
    typing["taken"] = [False, True]
    run(receipt.deliver_to_woken("ses_x", TEXT))
    assert typing["asked"] == [receipt.TAKEN_WAIT_SEC - receipt.CONFIRM_TIMEOUT_SEC, receipt.ENTER_AGAIN_SEC]


def test_a_text_left_in_the_input_is_given_up_after_the_rescue_time(typing, pane, short_rescue):
    pane["screens"] = ["│ > [Pasted text #1 +4 lines]\n" + CLAUDE_SCREEN]
    assert run(receipt.deliver_to_woken("ses_x", TEXT)) is False
    assert typing["typed"] == 1 and typing["enters"] >= 2


def test_a_text_that_is_gone_is_typed_once_more_and_never_a_third_time(typing, short_rescue):
    assert run(receipt.deliver_to_woken("ses_x", TEXT)) is False
    assert (typing["typed"], typing["enters"]) == (2, 0)


def test_a_text_left_in_the_input_when_the_rescue_stops_is_cleared_so_the_refusal_holds(typing, pane, short_rescue):
    # Left there, it would go in with the next Enter, on top of the message the sender sends again.
    pane["screens"] = ["│ > [Pasted text #1 +4 lines]\n" + CLAUDE_SCREEN]
    assert run(receipt.deliver_to_woken("ses_x", TEXT)) is False
    assert typing["keys"] == ["C-u"]


def test_a_text_that_is_gone_when_the_rescue_stops_leaves_the_input_alone(typing, short_rescue):
    assert run(receipt.deliver_to_woken("ses_x", TEXT)) is False
    assert typing["keys"] == []


def test_a_text_taken_after_enters_is_not_cleared(typing, pane):
    pane["screens"] = ["│ > Sent by the client (the operator did not type this):\n" + CLAUDE_SCREEN]
    typing["taken"] = [False, False, True]
    assert run(receipt.deliver_to_woken("ses_x", TEXT)) is True
    assert typing["keys"] == []


def test_a_launch_in_flight_is_waited_for_before_typing_so_the_text_is_not_held_twice(typing, monkeypatch):
    # Typing while the launch starts hands the text to the launch's held messages, and the rescue typing it again
    # would hold it a second time: the receiver got each message twice.
    calls = {"launching": True, "waited": 0}

    async def launched(_sid):
        calls["waited"] += 1
        calls["launching"] = False
        return True
    monkeypatch.setattr(receipt.input_ready, "launching", lambda _sid: calls["launching"])
    monkeypatch.setattr(receipt.input_ready, "wait_launched", launched)
    typing["confirmed"] = True
    assert run(receipt.deliver_to_woken("ses_x", TEXT)) is True
    assert (calls["waited"], typing["typed"]) == (1, 1)


def test_a_launch_given_up_is_not_typed_into(typing, monkeypatch):
    async def given_up(_sid):
        return False
    monkeypatch.setattr(receipt.input_ready, "launching", lambda _sid: True)
    monkeypatch.setattr(receipt.input_ready, "wait_launched", given_up)
    assert run(receipt.deliver_to_woken("ses_x", TEXT)) is False
    assert typing["typed"] == 0


def test_a_typing_that_failed_is_not_waited_on(typing, monkeypatch):
    async def failed(session_id, payload, key=None, **_):
        return {"ok": False}
    monkeypatch.setattr(receipt, "pty_send", failed)
    assert run(receipt.deliver_to_woken("ses_x", TEXT)) is False
    assert typing["asked"] == []


def test_a_message_queued_while_claude_answers_is_taken_without_an_enter(monkeypatch, pane, tmp_path):
    """Claude was answering the message typed before: this one is queued and shows in the input box until the turn's
    next break, and no row of a person's prompt is written for it. The row of its queueing says it was taken."""
    record = tmp_path / "r.jsonl"
    record.write_text("")
    log = {"enters": 0}

    async def pty_send(session_id, payload, key=None, **_):
        with record.open("a") as out:
            out.write(json.dumps({"type": "queue-operation", "operation": "enqueue", "content": payload["text"]}) + "\n")
        return {"ok": True, "confirmed": False}

    def keys(session_id, text=None, key=None, enter=False):
        log["enters"] += 1
        return True
    monkeypatch.setattr(receipt, "pty_send", pty_send)
    monkeypatch.setattr(receipt, "tmux_send_keys", keys)
    monkeypatch.setattr(receipt, "jsonl_path_for_session", lambda _sid: record)
    pane["screens"] = ["│ > Sent by the client (the operator did not type this):\n" + CLAUDE_SCREEN]
    assert run(receipt.deliver_to_woken("ses_x", TEXT)) is True
    assert log["enters"] == 0


@pytest.fixture
def launched(typing, monkeypatch):
    """The typing started the tab's claude (= `pty_send` answers `launched`): the launch has the text. `seen` is what
    the wait for the text's row answers."""
    log = {"watched": [], "seen": True}

    async def pty_send(session_id, payload, key=None, **_):
        typing["typed"] += 1
        return {"ok": True, "launched": True}

    async def wait_text_row(path, initial_pos, timeout, text, *, follow):
        log["watched"].append((path, initial_pos, timeout))
        return log["seen"]

    async def announced(_sid):
        return True
    monkeypatch.setattr(receipt, "pty_send", pty_send)
    monkeypatch.setattr(receipt, "wait_text_row", wait_text_row)
    monkeypatch.setattr(receipt.input_ready, "wait_launched", announced)
    return log


def test_a_text_handed_to_a_launch_is_watched_for_and_never_typed_again(typing, launched):
    # The record of a conversation that has not begun shows nothing yet: that is not a text that is gone.
    assert run(receipt.deliver_to_woken("ses_x", TEXT)) is True
    assert (typing["typed"], typing["enters"], typing["asked"]) == (1, 0, [])
    assert len(launched["watched"]) == 1


def test_a_text_handed_to_a_launch_that_does_not_show_is_refused_without_a_second_typing(typing, launched, short_rescue):
    launched["seen"] = False
    assert run(receipt.deliver_to_woken("ses_x", TEXT)) is False
    assert (typing["typed"], typing["enters"], typing["keys"]) == (1, 0, [])


def test_a_text_handed_to_a_launch_that_is_given_up_is_refused(typing, launched, monkeypatch):
    async def given_up(_sid):
        return False
    monkeypatch.setattr(receipt.input_ready, "wait_launched", given_up)
    assert run(receipt.deliver_to_woken("ses_x", TEXT)) is False
    assert (typing["typed"], launched["watched"]) == (1, [])


def test_the_watch_for_a_launched_text_lasts_as_long_as_the_held_message_gets(typing, launched):
    run(receipt.deliver_to_woken("ses_x", TEXT))
    assert launched["watched"][0][2] == receipt.SCREEN_WAIT_SEC + receipt.RESCUE_SEC


def test_a_text_the_send_kept_for_a_window_is_taken_and_not_typed_again(typing, monkeypatch):
    """`window_hold` types a kept text itself, once, when the window is gone: the rescue must not type it a second time."""
    async def kept(session_id, payload, key=None, **_):
        typing["typed"] += 1
        return {"ok": True, "held": "window"}
    monkeypatch.setattr(receipt, "pty_send", kept)
    assert run(receipt.deliver_to_woken("ses_x", TEXT)) == receipt.HELD
    assert (typing["typed"], typing["enters"], typing["asked"]) == (1, 0, [])


def test_a_text_typed_again_that_the_send_kept_is_held_and_not_typed_a_third_time(typing, pane, short_rescue, monkeypatch):
    """The first typing was lost (the text is gone from the input) and a window is open now: the typing again is kept, and
    the answer is that it is held."""
    answers = [{"ok": True, "confirmed": False}, {"ok": True, "held": "window"}]

    async def pty_send(session_id, payload, key=None, **_):
        typing["typed"] += 1
        return answers.pop(0)
    monkeypatch.setattr(receipt, "pty_send", pty_send)
    pane["screens"] = [CLAUDE_SCREEN]
    assert run(receipt.deliver_to_woken("ses_x", TEXT)) == receipt.HELD
    assert typing["typed"] == 2 and typing["enters"] == 0


def test_a_command_the_send_refused_at_a_window_is_not_taken(typing, monkeypatch):
    async def refused(session_id, payload, key=None, **kwargs):
        typing["typed"] += 1
        assert kwargs["hold"] is False
        return {"ok": False, "reason": "window_open"}
    monkeypatch.setattr(receipt, "pty_send", refused)
    assert run(receipt.deliver_to_woken("ses_x", TEXT, hold=False)) is False


def test_no_enter_is_typed_for_a_waiting_text_while_a_window_is_open(typing, pane, short_rescue, monkeypatch):
    """An Enter typed at a window confirms its first choice: the rescue leaves the waiting text alone until it is gone."""
    monkeypatch.setattr(receipt.window_answer, "look", lambda _sid: read_screen(screens.approval()))
    pane["screens"] = ["│ > Sent by the client (the operator did not type this):\n" + CLAUDE_SCREEN]
    assert run(receipt.deliver_to_woken("ses_x", TEXT)) is False
    assert (typing["enters"], typing["keys"]) == (0, [])


def test_the_text_waiting_in_the_input_is_not_cleared_at_a_window_either(typing, pane, short_rescue, monkeypatch):
    monkeypatch.setattr(receipt.window_answer, "look", lambda _sid: read_screen(screens.approval()))
    pane["screens"] = ["│ > [Pasted text #1 +4 lines]\n" + CLAUDE_SCREEN]
    run(receipt.deliver_to_woken("ses_x", TEXT))
    assert typing["keys"] == []
