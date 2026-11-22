"""The client's own messages to tabs (`backend/accounts/client_message.py`) are typed into the tabs agents work in,
and never into a tab set up for a program to ask: the program asks again itself."""
from __future__ import annotations

import pytest

from backend._internal.stop_signal import BackendStopping
from backend.accounts import client_message
from backend.tests.async_run import run


@pytest.fixture
def tabs(monkeypatch):
    """Two tabs, one set up for asks; what was typed into which, and which were woken."""
    seen = {"woken": [], "typed": []}

    async def wake(session_id: str) -> bool:
        seen["woken"].append(session_id)
        return False

    async def deliver(session_id: str, text: str, woke: bool) -> dict:
        seen["typed"].append((session_id, text))
        return {"ok": True}

    monkeypatch.setattr(client_message, "takes_asks", lambda session_id: session_id == "ses_asked")
    monkeypatch.setattr(client_message, "wake_tab", wake)
    monkeypatch.setattr(client_message, "deliver_message", deliver)
    return seen


def test_a_working_tab_is_woken_and_typed_into(tabs):
    assert run(client_message.send_to_tab("ses_worker", "carry on")) is True
    assert tabs == {"woken": ["ses_worker"], "typed": [("ses_worker", "carry on")]}


def test_a_tab_set_up_for_asks_is_neither_woken_nor_typed_into_and_counts_as_told(tabs):
    assert run(client_message.send_to_tab("ses_asked", "carry on")) is True
    assert tabs == {"woken": [], "typed": []}


def test_a_tab_that_is_not_waited_for_because_the_backend_stops_is_not_told(tabs, monkeypatch):
    async def wake(session_id: str) -> bool:
        raise BackendStopping
    monkeypatch.setattr(client_message, "wake_tab", wake)
    assert run(client_message.send_to_tab("ses_worker", "carry on")) is False
    assert tabs["typed"] == []
