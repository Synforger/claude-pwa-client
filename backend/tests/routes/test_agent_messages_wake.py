"""A message to a tab whose claude it had to start: typed only once the screen is Claude's, and only said to have
arrived when the tab took it (`routes/agent_messages.py`, `terminal/receipt.py`)."""
from __future__ import annotations

import pytest

import backend.routes.agent_messages as am
from backend.tests.routes.test_agent_messages import (  # noqa: F401  (= fixtures of the tests of the same door)
    _send, client, no_tmux, started, tabs, typed,
)


def _code(response) -> tuple[int, str]:
    return response.status_code, response.json()["detail"]["code"]


def test_a_started_claude_is_typed_to_only_once_its_screen_is_claudes(client, tabs, typed, started, no_tmux, monkeypatch):
    looked_when_typed: list[int] = []

    async def screen(session_id):
        looked_when_typed.append(len(typed))
        return True
    monkeypatch.setattr(am, "wait_for_claude_screen", screen)
    monkeypatch.setattr(am.input_ready, "wait_ready", _ready)
    assert _send(client, to="ses_idle").status_code == 200
    assert looked_when_typed == [0] and len(typed) == 1               # the look came before anything was typed


def test_a_claude_whose_screen_never_comes_gets_nothing_typed(client, tabs, typed, started, no_tmux, monkeypatch):
    async def never(session_id):
        return False
    monkeypatch.setattr(am, "wait_for_claude_screen", never)
    monkeypatch.setattr(am.input_ready, "wait_ready", _ready)
    r = _send(client, to="ses_idle")
    assert _code(r) == (409, "agent_message_receiver_not_ready") and typed == []


def test_a_message_the_woken_tab_did_not_take_is_refused_not_said_to_have_arrived(
        client, tabs, typed, started, no_tmux, monkeypatch):
    async def not_taken(session_id, text):
        return False
    monkeypatch.setattr(am, "deliver_to_woken", not_taken)
    monkeypatch.setattr(am.input_ready, "wait_ready", _ready)
    r = _send(client, to="ses_idle")
    assert _code(r) == (409, "agent_message_not_taken")
    assert "もう一度送ってください" in r.json()["detail"]["message"]


def test_a_tab_that_was_running_is_said_to_have_got_the_message_though_nothing_confirms_it(client, tabs, typed, monkeypatch):
    sent: list[str] = []

    async def unconfirmed(session_id, payload, idempotency_key=None):
        sent.append(session_id)
        return {"ok": True, "confirmed": False}      # a turn in progress writes no row

    async def must_not_be_asked(*_a):
        raise AssertionError("a running tab is not waited for or checked")
    monkeypatch.setattr(am, "pty_send", unconfirmed)
    monkeypatch.setattr(am, "wait_for_claude_screen", must_not_be_asked)
    monkeypatch.setattr(am, "deliver_to_woken", must_not_be_asked)
    r = _send(client)
    assert r.status_code == 200 and r.json()["ok"] is True and sent == ["ses_receiver"]


def test_the_message_of_the_clients_own_features_goes_through_the_same_door(tabs, typed, started, no_tmux, monkeypatch):
    from backend.accounts.client_message import send_to_tab  # noqa: PLC0415
    from backend.tests.async_run import run  # noqa: PLC0415
    monkeypatch.setattr(am.input_ready, "wait_ready", _ready)
    assert run(send_to_tab("ses_idle", "carry on")) is True                   # woken: delivered and checked
    assert typed[-1] == ("ses_idle", {"text": "carry on", "enter": True})

    async def not_taken(session_id, text):
        return False
    monkeypatch.setattr(am, "deliver_to_woken", not_taken)
    assert run(send_to_tab("ses_idle", "carry on")) is False                  # a refusal is not a delivery


async def _ready(session_id, timeout=None):
    return True
