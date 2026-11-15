"""A message that fails always says why, with a code that tells the sender whether it may have reached the receiver
(`routes/agent_messages.py`): nothing was typed (`agent_message_receiver_not_ready`, `agent_message_not_sent`: send
again), or something was typed and its arrival is not known (`agent_message_unconfirmed`: check before sending again)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import backend.routes.agent_messages as am
from backend.peers import peer_call
from backend.tests.routes.test_agent_messages import (  # noqa: F401  (= fixtures of the tests of the same door)
    _peers, _send, client, tabs, typed,
)


def _detail(response) -> dict:
    return response.json()["detail"]


def _pty_send_answers(monkeypatch, answer) -> list[str]:
    """`pty_send` answers `answer` (or raises it, when it is an exception). Returns the tabs it was asked to type to."""
    asked: list[str] = []

    async def pty_send(session_id, payload, idempotency_key=None):
        asked.append(session_id)
        if isinstance(answer, BaseException):
            raise answer
        return answer
    monkeypatch.setattr(am, "pty_send", pty_send)
    return asked


@pytest.mark.parametrize("reason", ["not_ready", "launch_failed"])
def test_a_typing_that_typed_nothing_says_so_and_asks_to_send_again(client, tabs, typed, monkeypatch, reason):
    _pty_send_answers(monkeypatch, {"ok": False, "reason": reason})
    r = _send(client)
    assert (r.status_code, _detail(r)["code"]) == (409, "agent_message_receiver_not_ready")
    assert "何も打っていません" in _detail(r)["message"]


def test_a_typing_that_stopped_part_way_says_the_message_may_have_arrived(client, tabs, typed, monkeypatch):
    _pty_send_answers(monkeypatch, {"ok": False})
    r = _send(client)
    assert (r.status_code, _detail(r)["code"]) == (500, "agent_message_unconfirmed")
    assert "届いているかもしれません" in _detail(r)["message"]


@pytest.mark.parametrize("error", [RuntimeError("tmux went away"), HTTPException(404, "unknown session")])
def test_an_error_while_typing_says_the_message_may_have_arrived(client, tabs, typed, monkeypatch, error):
    _pty_send_answers(monkeypatch, error)
    r = _send(client)
    assert (r.status_code, _detail(r)["code"]) == (500, "agent_message_unconfirmed")


def test_an_error_before_anything_is_typed_says_nothing_was_sent(client, tabs, typed, monkeypatch):
    asked = _pty_send_answers(monkeypatch, {"ok": True})

    async def broken_wake(tab_id):
        raise OSError("no tmux server")
    monkeypatch.setattr(am, "wake_tab", broken_wake)
    r = _send(client)
    assert (r.status_code, _detail(r)["code"]) == (500, "agent_message_not_sent")
    assert "何も届いていません" in _detail(r)["message"] and asked == []


def test_an_error_in_the_checks_before_the_typing_says_nothing_was_sent(client, tabs, typed, monkeypatch):
    async def broken_check(receiver_id, text):
        raise KeyError("ses_receiver")
    monkeypatch.setattr(am, "check", broken_check)
    r = _send(client)
    assert (r.status_code, _detail(r)["code"]) == (500, "agent_message_not_sent")
    assert typed == []


def test_an_error_that_already_has_a_code_is_not_renamed(client, tabs, typed, monkeypatch):
    r = _send(client, to="nobody")
    assert (r.status_code, _detail(r)["code"]) == (404, "agent_message_unknown_receiver")


def test_a_message_that_arrived_is_not_called_a_failure_when_the_child_s_memo_cannot_be_written(
        client, tabs, typed, monkeypatch):
    def broken_memo(sender, receiver):
        raise PermissionError("memo is read-only")
    monkeypatch.setattr(am, "hand_work", broken_memo)
    r = _send(client)
    assert r.status_code == 200 and r.json()["ok"] is True and len(typed) == 1


def test_a_message_relayed_from_another_machine_fails_with_codes_too(client, tabs, typed, monkeypatch, tmp_path):
    _peers(monkeypatch, tmp_path)
    from backend.tests.routes.test_agent_messages import _from_peer, _relay  # noqa: PLC0415
    _pty_send_answers(monkeypatch, {"ok": False})
    r = _relay(_from_peer())
    assert (r.status_code, _detail(r)["code"]) == (500, "agent_message_unconfirmed")

    async def broken_check(receiver_id, text):
        raise KeyError("ses_receiver")
    monkeypatch.setattr(am, "check", broken_check)
    r = _relay(_from_peer())
    assert (r.status_code, _detail(r)["code"]) == (500, "agent_message_not_sent")


def test_a_call_to_another_machine_that_breaks_after_it_was_made_says_the_message_may_have_arrived(
        client, tabs, typed, monkeypatch, tmp_path):
    _peers(monkeypatch, tmp_path)

    def broken(url, payload, timeout):
        raise ValueError("answer cut off")
    monkeypatch.setattr(peer_call, "_call_peer", broken)
    r = _send(client, to="home:notes")
    assert (r.status_code, _detail(r)["code"]) == (500, "agent_message_unconfirmed")


def test_another_machine_s_failure_with_no_reason_is_not_said_to_be_a_plain_refusal(
        client, tabs, typed, monkeypatch, tmp_path):
    _peers(monkeypatch, tmp_path)
    monkeypatch.setattr(peer_call, "_call_peer", lambda url, payload, timeout: (500, {}))
    r = _send(client, to="home:notes")
    assert (r.status_code, _detail(r)["code"]) == (500, "agent_message_peer_failed")
    assert "届いたかもしれない" in _detail(r)["message"]
