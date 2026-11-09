"""Getting a message into a tab whose claude was just started (`terminal/receipt.py`): the screen is waited for, and
the message is looked for in the record, with one rescue."""
from __future__ import annotations

import json

import pytest

import backend.terminal.receipt as receipt
from backend.tests.async_run import run

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
    log = {"typed": 0, "enters": 0, "taken": [], "asked": [], "confirmed": False}

    async def pty_send(session_id, payload, key=None):
        log["typed"] += 1
        return {"ok": True, "confirmed": log["confirmed"]}

    async def taken(session_id, initial_pos, timeout, text):
        log["asked"].append(timeout)
        answers = log["taken"]
        return answers[min(len(log["asked"]), len(answers)) - 1] if answers else False

    def keys(session_id, text=None, key=None, enter=False):
        log["enters"] += 1 if enter and text is None else 0
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


def test_a_message_that_never_comes_is_refused_after_one_rescue_and_no_more(typing, pane):
    pane["screens"] = ["│ > [Pasted text #1 +4 lines]\n" + CLAUDE_SCREEN]
    assert run(receipt.deliver_to_woken("ses_x", TEXT)) is False
    assert (typing["typed"], typing["enters"]) == (1, 1)
    typing["asked"].clear()
    pane["screens"] = [CLAUDE_SCREEN]
    assert run(receipt.deliver_to_woken("ses_x", TEXT)) is False
    assert typing["typed"] == 3 and typing["enters"] == 1                    # the second try typed once more, never more


def test_a_typing_that_failed_is_not_waited_on(typing, monkeypatch):
    async def failed(session_id, payload, key=None):
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

    async def pty_send(session_id, payload, key=None):
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
