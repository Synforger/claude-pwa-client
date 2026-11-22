"""A message for a machine that sleeps is kept, and arrives once when the machine is back (`backend/peers/`). Both machines
are this one app: the sending side's call to the other backend is answered by the receiving routes, called from the
configured peer's address (= the same stand-in `test_agent_messages.py` uses); tmux and claude are not started."""
from __future__ import annotations

import json
import urllib.error

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import backend._common.config as config_mod
from backend._common.state import SessionDef
from backend.peers import outbox_store, peer_call, peer_health_store, peer_patrol, seen_message_ids
from backend.routes import agent_messages as am
from backend.tests.async_run import run

PEER_ADDRESS = "100.64.0.2"
DOWN = urllib.error.URLError(ConnectionRefusedError("refused"))


@pytest.fixture
def tabs(isolated_state):
    for sid, title in (("ses_sender", "tools"), ("ses_receiver", "client work")):
        isolated_state.sessions_meta[sid] = SessionDef(id=sid, agent_id="agent_a", title=title, created_at=0)
    return isolated_state.sessions_meta


@pytest.fixture
def typed(monkeypatch) -> list[tuple[str, str]]:
    """What was typed into a tab, as (tab id, text); both tabs have a claude running."""
    calls: list[tuple[str, str]] = []

    async def fake_send(session_id, payload, idempotency_key=None):
        calls.append((session_id, payload["text"]))
        return {"ok": True, "delivered": True}

    monkeypatch.setattr(am, "pty_send", fake_send)
    monkeypatch.setattr(am, "claude_in_pane", lambda sid: True)
    monkeypatch.setattr(am, "scan_panes", lambda sids: {
        sid: am.PaneState(has_session=am.has_tmux_session(sid), runs_claude=am.claude_in_pane(sid)) for sid in sids})
    return calls


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(am.router)
    return TestClient(app)


@pytest.fixture
def machine(monkeypatch, tmp_path, tabs, typed, client):
    """The other machine, reached through `home`. `machine.up` says whether its backend answers; `machine.lose_answers`
    is how many answers are lost on the way back (= the backend did its work, the sender gets a timeout)."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"uploads_tmp": str(tmp_path / "uploads"), "agent_message_peers": {
        "home": {"url": "http://peer.test", "address": PEER_ADDRESS}}}))
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)
    config_mod.get_config.cache_clear()
    far = TestClient(FastAPI(), client=(PEER_ADDRESS, 50000))
    far.app.include_router(am.router)

    class Machine:
        up = True
        lose_answers = 0

    state = Machine()

    def through(url, payload, timeout):
        path = url.removeprefix("http://peer.test")
        if not state.up:
            raise DOWN
        r = far.post(path, json=payload) if payload is not None else far.get(path)
        if state.lose_answers and payload is not None:
            state.lose_answers -= 1
            raise TimeoutError("timed out")
        return r.status_code, r.json()

    monkeypatch.setattr(peer_call, "_call_peer", through)
    return state


def _send(client, to="home:ses_receiver", text="hello", **form):
    return client.post("/agent-messages", data={"to": to, "from": "ses_sender", "text": text, **form})


def _to_receiver(typed) -> list[str]:
    """The bodies of what reached the receiving tab (= the part between the envelope's tags)."""
    return [text.split("\n")[2] for tab, text in typed if tab == "ses_receiver"]


def _notices(typed) -> list[str]:
    return [text for tab, text in typed if tab == "ses_sender"]


# --- a machine that sleeps -------------------------------------------------------------------------


def test_a_message_sent_while_the_machine_sleeps_arrives_once_when_it_is_back(client, machine, typed):
    machine.up = False
    r = _send(client, text="read this when you wake")
    assert r.status_code == 200 and r.json()["outbox"] is True and r.json()["to"] == "home:ses_receiver"
    assert typed == [] and len(outbox_store.pending("home")) == 1

    machine.up = True
    run(peer_patrol.tick())
    assert _to_receiver(typed) == ["read this when you wake"]
    assert outbox_store.pending() == []
    (notice,) = _notices(typed)
    assert 'event="delivered" to="home:ses_receiver"' in notice
    run(peer_patrol.tick())
    assert _to_receiver(typed) == ["read this when you wake"]        # nothing more is sent


def test_messages_kept_in_a_night_arrive_in_the_order_they_were_sent(client, machine, typed):
    machine.up = False
    for number in range(1, 5):
        assert _send(client, text=f"message {number}").json()["outbox"] is True
    machine.up = True
    run(peer_patrol.tick())
    assert _to_receiver(typed) == [f"message {number}" for number in range(1, 5)]
    assert len(_notices(typed)) == 4


def test_a_message_sent_the_moment_the_machine_is_back_does_not_overtake_the_kept_ones(client, machine, typed):
    machine.up = False
    _send(client, text="first")
    machine.up = True                                                # the watch has not looked yet
    assert _send(client, text="second").json()["outbox"] is True
    run(peer_patrol.tick())
    assert _to_receiver(typed) == ["first", "second"]


def test_a_machine_that_answers_gets_the_message_at_once_and_nothing_is_kept(client, machine, typed):
    r = _send(client, text="now")
    assert r.json()["delivered"] is True and "outbox" not in r.json()
    assert _to_receiver(typed) == ["now"] and outbox_store.pending() == []


def test_the_watch_writes_down_that_the_machine_was_down_and_is_back(client, machine, typed):
    machine.up = False
    _send(client)
    down = peer_health_store.get("home")
    assert (down["ok"], down["last_error"]) == (False, "unreachable")
    machine.up = True
    run(peer_patrol.tick())
    assert peer_health_store.get("home")["ok"] is True


# --- the same message sent twice ----------------------------------------------------------------


def test_a_message_the_machine_took_but_whose_answer_was_lost_is_not_typed_twice(client, machine, typed):
    machine.lose_answers = 1
    r = _send(client, text="did it arrive?")
    assert r.json()["outbox"] is True                                # the sender cannot know: it is kept
    assert _to_receiver(typed) == ["did it arrive?"]                 # ... but the machine had it
    run(peer_patrol.tick())
    assert _to_receiver(typed) == ["did it arrive?"]                 # sent again with its id: not typed again
    assert outbox_store.pending() == []
    assert "has arrived" in _notices(typed)[0]


def test_a_message_still_being_delivered_is_kept_and_sent_again_on_the_next_look(client, machine, typed):
    machine.up = False
    _send(client, text="slow tab")
    [entry] = outbox_store.pending("home")
    seen_message_ids.claim(entry["id"])                              # the first delivery has not finished
    machine.up = True
    run(peer_patrol.tick())
    assert _to_receiver(typed) == [] and len(outbox_store.pending("home")) == 1
    seen_message_ids.release(entry["id"])
    run(peer_patrol.tick())
    assert _to_receiver(typed) == ["slow tab"] and outbox_store.pending() == []


def test_a_message_from_a_backend_without_ids_is_typed_every_time(machine, typed):
    far = TestClient(FastAPI(), client=(PEER_ADDRESS, 50000))
    far.app.include_router(am.router)
    body = {"to": "ses_receiver", "from_title": "tools", "from_session": "ses_far", "text": "no id"}
    for _ in range(2):
        assert far.post(am.RELAYED_PATH, json=body).json()["ok"] is True
    assert _to_receiver(typed) == ["no id", "no id"]


def test_a_relayed_message_with_a_badly_written_id_is_refused(machine, typed):
    far = TestClient(FastAPI(), client=(PEER_ADDRESS, 50000))
    far.app.include_router(am.router)
    body = {"to": "ses_receiver", "from_title": "tools", "from_session": "ses_far", "text": "x", "message_id": "short"}
    r = far.post(am.RELAYED_PATH, json=body)
    assert (r.status_code, r.json()["detail"]["code"]) == (400, "agent_message_bad_relay") and typed == []


def test_the_same_id_a_second_time_is_answered_as_a_duplicate_and_typed_once(machine, typed):
    far = TestClient(FastAPI(), client=(PEER_ADDRESS, 50000))
    far.app.include_router(am.router)
    body = {"to": "ses_receiver", "from_title": "tools", "from_session": "ses_far", "text": "once", "message_id": "a" * 32}
    first, second = (far.post(am.RELAYED_PATH, json=body) for _ in range(2))
    assert first.json()["ok"] is True and "duplicate" not in first.json()
    assert second.json() == {"ok": True, "duplicate": True, "to": "ses_receiver", "operator_said": False}
    assert _to_receiver(typed) == ["once"]


def test_a_delivery_that_failed_does_not_use_the_id_up(machine, typed, monkeypatch):
    far = TestClient(FastAPI(), client=(PEER_ADDRESS, 50000))
    far.app.include_router(am.router)
    body = {"to": "ses_receiver", "from_title": "tools", "from_session": "ses_far", "text": "retry me", "message_id": "b" * 32}
    monkeypatch.setattr(am, "claude_in_pane", lambda sid: False)
    monkeypatch.setattr(am, "has_tmux_session", lambda sid: True)
    monkeypatch.setattr(am, "resume_command_for", lambda sid: None)
    monkeypatch.setattr(am, "uses_launcher", lambda sid: False)
    assert far.post(am.RELAYED_PATH, json=body).json()["detail"]["code"] == "agent_message_receiver_not_running"
    monkeypatch.setattr(am, "claude_in_pane", lambda sid: True)
    assert far.post(am.RELAYED_PATH, json=body).json()["ok"] is True
    assert _to_receiver(typed) == ["retry me"]


# --- inside this machine ------------------------------------------------------------------------


def test_a_message_on_this_machine_with_the_same_id_twice_is_typed_once(client, tabs, typed):
    first = _send(client, to="ses_receiver", text="once", message_id="c" * 32)
    second = _send(client, to="ses_receiver", text="once", message_id="c" * 32)
    assert first.json()["delivered"] is True
    assert second.json() == {"ok": True, "duplicate": True, "to": "ses_receiver", "operator_said": False}
    assert _to_receiver(typed) == ["once"]


def test_a_message_on_this_machine_with_no_id_is_typed_every_time(client, tabs, typed):
    for _ in range(2):
        assert _send(client, to="ses_receiver", text="again").status_code == 200
    assert _to_receiver(typed) == ["again", "again"]


@pytest.mark.parametrize("message_id", ["short", "A" * 32, "g" * 32, "a" * 33])
def test_an_id_that_is_not_32_lowercase_hex_digits_is_refused(client, tabs, typed, message_id):
    r = _send(client, to="ses_receiver", message_id=message_id)
    assert (r.status_code, r.json()["detail"]["code"]) == (400, "agent_message_bad_id") and typed == []


def test_the_id_of_a_message_for_another_machine_is_the_sending_backend_s_own(client, machine, typed):
    machine.up = False
    _send(client, message_id="d" * 32)
    [entry] = outbox_store.pending("home")
    assert entry["id"] != "d" * 32 and len(entry["id"]) == 32


# --- refused when the machine is back -----------------------------------------------------------


def test_a_kept_message_for_a_tab_that_does_not_exist_is_dropped_and_its_sender_told(client, machine, typed):
    machine.up = False
    _send(client, to="home:nobody")
    machine.up = True
    run(peer_patrol.tick())
    assert outbox_store.pending() == [] and _to_receiver(typed) == []
    (notice,) = _notices(typed)
    assert 'event="refused"' in notice and "no such tab on that machine" in notice


def test_a_message_the_machine_refuses_when_sent_at_once_is_not_kept(client, machine, typed):
    r = _send(client, to="home:nobody")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "agent_message_unknown_receiver"
    assert outbox_store.pending() == []


def test_a_typing_that_answered_not_ok_does_not_use_the_id_up(machine, typed, monkeypatch):
    # The typing into a running tab answers `ok: false` without raising; the same id must still go in on the next try.
    far = TestClient(FastAPI(), client=(PEER_ADDRESS, 50000))
    far.app.include_router(am.router)
    body = {"to": "ses_receiver", "from_title": "tools", "from_session": "ses_far", "text": "retry me", "message_id": "d" * 32}
    real = am.deliver_or_keep

    async def not_typed(tab_id, text):
        return {"ok": False, "reason": "send_failed"}
    monkeypatch.setattr(am, "deliver_or_keep", not_typed)
    assert far.post(am.RELAYED_PATH, json=body).json()["ok"] is False
    monkeypatch.setattr(am, "deliver_or_keep", real)
    answer = far.post(am.RELAYED_PATH, json=body).json()
    assert answer["ok"] is True and "duplicate" not in answer
    assert _to_receiver(typed) == ["retry me"]


def test_a_message_that_may_have_arrived_is_not_typed_again_with_the_same_id(machine, typed, monkeypatch):
    # The typing stopped part way: the message may be in the receiver already, so a resend must not add a second copy.
    far = TestClient(FastAPI(), client=(PEER_ADDRESS, 50000))
    far.app.include_router(am.router)
    body = {"to": "ses_receiver", "from_title": "tools", "from_session": "ses_far", "text": "maybe in", "message_id": "e" * 32}
    real = am.deliver_or_keep

    async def stopped_part_way(tab_id, text):
        am.raise_error(500, am.UNCONFIRMED_CODE, am.UNCONFIRMED_MESSAGE)
    monkeypatch.setattr(am, "deliver_or_keep", stopped_part_way)
    assert far.post(am.RELAYED_PATH, json=body).json()["detail"]["code"] == am.UNCONFIRMED_CODE
    monkeypatch.setattr(am, "deliver_or_keep", real)
    assert far.post(am.RELAYED_PATH, json=body).json()["duplicate"] is True
    assert _to_receiver(typed) == []
