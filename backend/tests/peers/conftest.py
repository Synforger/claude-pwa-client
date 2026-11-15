"""Fixtures for the tests of `backend/peers/`: one configured machine (`home`), a stand-in for its backend, and the sender's
tab, whose notices are collected."""
from __future__ import annotations

import json
import urllib.error

import pytest

import backend._common.config as config_mod
from backend._common.state import SessionDef
from backend.peers import peer_call
from backend.routes import agent_messages as am

PEER_ADDRESS = "100.64.0.2"


@pytest.fixture
def home(monkeypatch, tmp_path):
    """The machine `home` is configured (= `agent_message_peers`)."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"uploads_tmp": str(tmp_path / "uploads"), "agent_message_peers": {
        "home": {"url": "http://peer.test", "address": PEER_ADDRESS}}}))
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)
    config_mod.get_config.cache_clear()
    return config_mod.AGENT_MESSAGE_PEERS["home"]


class FarMachine:
    """Stands in for the other machine's backend: what each call to it gets back. `script` is a list of answers used
    in order, then `default`; an answer is `(status, body)`, or an exception that the call raises."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict | None]] = []
        self.script: list = []
        self.default: object = (200, {"ok": True, "delivered": True, "to": "ses_far"})

    def __call__(self, url: str, payload: dict | None, timeout: float):
        self.calls.append((url, payload))
        answer = self.script.pop(0) if self.script else self.default
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def goes_down(self) -> None:
        """The machine cannot be reached (= connection refused)."""
        self.default = urllib.error.URLError(ConnectionRefusedError("refused"))

    def comes_back(self) -> None:
        self.default = (200, {"ok": True, "delivered": True, "to": "ses_far"})

    @property
    def relayed(self) -> list[dict]:
        """The messages handed over, in order."""
        return [payload for url, payload in self.calls if url.endswith(peer_call.RELAYED_PATH)]


@pytest.fixture
def far(monkeypatch) -> FarMachine:
    machine = FarMachine()
    monkeypatch.setattr(peer_call, "_call_peer", machine)
    return machine


@pytest.fixture
def sender(isolated_state, monkeypatch) -> list[tuple[str, str]]:
    """The tab `ses_sender`, whose claude runs. What it is told is collected as (tab id, text)."""
    isolated_state.sessions_meta["ses_sender"] = SessionDef(id="ses_sender", agent_id="agent_a", title="tools",
                                                            created_at=0)
    told: list[tuple[str, str]] = []

    async def deliver(tab_id, text, woke):
        told.append((tab_id, text))
        return {"ok": True}

    monkeypatch.setattr(am, "deliver_message", deliver)
    monkeypatch.setattr(am, "_tab_running", lambda tab_id: True)
    return told


@pytest.fixture(autouse=True)
def flush_locks(monkeypatch) -> None:
    """Each test starts with no flush running (= the locks are made on the loop the test runs on)."""
    from backend.peers import outbox_flush

    monkeypatch.setattr(outbox_flush, "_locks", {})


def kept_entry(entry_id: str, *, to: str = "notes", kept_at: float = 1_000.0, text: str = "hello") -> dict:
    """A message in the outbox for `home`."""
    return {"id": entry_id, "peer": "home", "to": to, "from_session": "ses_sender", "from_title": "tools",
            "text": text, "kept_at": kept_at, "tries": 0}
