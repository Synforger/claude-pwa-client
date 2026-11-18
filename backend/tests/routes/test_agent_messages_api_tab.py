"""A message to an API tab is refused with its own code at both doors that take one (`POST /agent-messages` from a tab of
this machine, `POST /agent-messages/relayed` from a peer machine): nobody reads it, and nothing is typed anywhere."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.routes.agent_messages as am
from backend.tests.api_tabs.samples import TAB_ID, write_config

PEER_ADDRESS = "100.64.0.2"


@pytest.fixture
def typed(monkeypatch) -> list[tuple[str, dict]]:
    """What the message path typed into a terminal (= it must stay empty)."""
    calls: list[tuple[str, dict]] = []

    async def fake_send(session_id, payload, idempotency_key=None):
        calls.append((session_id, payload))
    monkeypatch.setattr(am, "pty_send", fake_send)
    return calls


@pytest.fixture
def sender(isolated_state, api_env, monkeypatch):
    monkeypatch.setattr(isolated_state, "save_sessions_meta", lambda: None)
    return isolated_state.register_session("agent_a", title="sender")


def _local() -> TestClient:
    app = FastAPI()
    app.include_router(am.router)
    return TestClient(app)


@pytest.mark.parametrize("receiver", [TAB_ID, "Support bot"])
def test_a_message_from_a_tab_of_this_machine_is_refused_by_id_and_by_title(sender, typed, receiver):
    reply = _local().post("/agent-messages", data={"to": receiver, "from": sender.id, "text": "hello"})
    assert reply.status_code == 409
    assert reply.json()["detail"]["code"] == "agent_message_api_tab" and typed == []


def test_a_message_relayed_from_a_peer_machine_is_refused_the_same_way(sender, typed, api_env):
    write_config(api_env,
                 api_tabs={"support-bot": {"title": "Support bot", "agent_id": "agent_a", "record": str(api_env.record)}},
                 agent_message_peers={"home": {"url": "http://peer.test/", "address": PEER_ADDRESS}})
    app = FastAPI()
    app.include_router(am.router)
    peer = TestClient(app, client=(PEER_ADDRESS, 50000))
    for receiver in (TAB_ID, "Support bot"):
        reply = peer.post(am.RELAYED_PATH, json={"to": receiver, "from_title": "tools", "from_session": "ses_far",
                                                 "text": "hello"})
        assert reply.status_code == 409 and reply.json()["detail"]["code"] == "agent_message_api_tab"
    assert typed == []


def test_a_receiver_that_is_nothing_is_still_unknown(sender, typed):
    reply = _local().post("/agent-messages", data={"to": "api_nobody", "from": sender.id, "text": "hello"})
    assert reply.status_code == 404 and reply.json()["detail"]["code"] == "agent_message_unknown_receiver"
