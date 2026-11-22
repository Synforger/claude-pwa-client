"""The notice to the tab that wrote a kept message is not waited for when the backend stops (`peers/outbox_notify.py`):
the sender is not told, as when the tab is gone, and the kept message's own outcome stands."""
from __future__ import annotations

import pytest

from backend._common.state import SessionDef
from backend._internal.stop_signal import BackendStopping
from backend.peers import outbox_notify
from backend.routes import agent_messages
from backend.tests.async_run import run


def test_a_notice_that_the_stop_ends_is_not_delivered_and_not_an_error(isolated_state, monkeypatch):
    isolated_state.sessions_meta["ses_sender"] = SessionDef(id="ses_sender", agent_id="agent_a", title="tools", created_at=0)

    async def stopped(tab_id, text, woke):
        raise BackendStopping
    monkeypatch.setattr(agent_messages, "_tab_running", lambda tab_id: True)
    monkeypatch.setattr(agent_messages, "deliver_message", stopped)
    entry = {"id": "m1", "peer": "home", "to": "notes", "from_session": "ses_sender"}
    assert run(outbox_notify.notify_sender(entry, "the message was delivered")) is False
