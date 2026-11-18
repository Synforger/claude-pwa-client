"""How each door treats an API tab (`backend/api_tabs/`, design in `docs/reference/api-tabs.md`): the list, the overview and
the status channel show it, the replay and the subscription reach its record, and the doors that need a Claude Code
refuse it or leave it alone."""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import backend.jsonl.routes as jsonl_routes
import backend.routes.agent_messages as agent_messages
import backend.routes.overview as overview
import backend.routes.sessions as sessions
import backend.routes.unified_stream as us
import backend.terminal.session_resolver as session_resolver
import backend.usage.usage as usage_log
from backend._common import state as state_mod
from backend.api_tabs import stream
from backend.tests.api_tabs.samples import (
    TAB_ID, append, assistant_row, tool_result_row, tool_use_row, user_row, write_config)
from backend.tests.async_run import run

pytestmark = pytest.mark.usefixtures("api_env")


@pytest.fixture
def client(isolated_state, monkeypatch):
    monkeypatch.setattr(usage_log, "read_all_rate_limits_tail", lambda: [])
    monkeypatch.setattr(overview, "_read_rate_limits_tail_cached", lambda: [])
    app = FastAPI()
    app.include_router(sessions.router)
    app.include_router(overview.router)
    return TestClient(app)


def _claude_tab(state) -> state_mod.SessionDef:
    meta = state.register_session("agent_a", title="a Claude tab")
    state.stream_states[meta.id] = state_mod.StreamState(agent_id="agent_a")
    return meta


# --- the list, the overview, the status channel ---

def test_the_list_carries_an_api_row_that_sessions_meta_does_not_hold(client, isolated_state, api_env, monkeypatch):
    monkeypatch.setattr(isolated_state, "save_sessions_meta", lambda: None)
    claude = _claude_tab(isolated_state)
    append(api_env.record, assistant_row("a1", "m1", "hi", usage={"input_tokens": 12300}))
    asyncio.run(stream.poll())
    rows = {row["id"]: row for row in client.get("/sessions").json()}
    row = rows[TAB_ID]
    assert (row["kind"], row["title"], row["agent_id"], row["account_id"], row["tier"], row["asleep"]) == (
        "api", "Support bot", "agent_a", "api", None, False)
    assert row["context_tokens"] == 12300
    assert "kind" not in rows[claude.id]                        # the Claude tabs' rows are as they were
    assert TAB_ID not in state_mod.sessions_meta and list(rows) == [claude.id, TAB_ID]


def test_the_overview_has_the_same_ids_as_the_list_and_shows_no_progress_marks(client, isolated_state, api_env, monkeypatch):
    monkeypatch.setattr(isolated_state, "save_sessions_meta", lambda: None)
    _claude_tab(isolated_state)
    append(api_env.record, assistant_row("a1", "m1", "hi", usage={"input_tokens": 5}))
    asyncio.run(stream.poll())
    listed = {row["id"] for row in client.get("/sessions").json()}
    body = client.get("/sessions/overview").json()
    assert set(body) == listed                                  # else the screen would fetch the list again for ever
    row = body[TAB_ID]
    assert (row["busy"], row["waiting_input"], row["asleep"], row["tier"], row["context_tokens"]) == (
        False, False, False, None, 5)
    assert body == overview._build_sessions_overview()


def test_the_status_channel_gives_an_api_row_of_its_own_kind_and_leaves_the_claude_rows_alone(isolated_state, api_env):
    claude = _claude_tab(isolated_state)
    api_env.spend.write_text(json.dumps({"month": __import__("datetime").datetime.now().strftime("%Y-%m"),
                                         "spent": 7, "limit": 100, "currency": "JPY"}))
    append(api_env.record, assistant_row("a1", "m1", "hi", usage={"input_tokens": 40}))
    asyncio.run(stream.poll())
    status = overview._build_all_status()
    assert set(status[TAB_ID]) == {"kind", "context_tokens", "context_window", "spend", "spend_scope"}  # no 5h, 7d or ctx: no NaN%
    assert (status[TAB_ID]["kind"], status[TAB_ID]["context_tokens"], status[TAB_ID]["spend"]["spent"]) == ("api", 40, 7)
    assert "kind" not in status[claude.id] and "ctx_pct" in status[claude.id] and "five_hour_pct" in status[claude.id]


def test_seen_is_accepted_for_an_api_tab_and_an_unknown_id_is_still_404(client):
    reply = client.post(f"/sessions/{TAB_ID}/seen")
    assert reply.status_code == 200 and state_mod.session_last_seen_at[TAB_ID] == reply.json()["last_seen_at"]
    assert client.post("/sessions/api_nobody/seen").status_code == 404
    assert client.post("/sessions/ses_nobody/seen").status_code == 404


def test_the_doors_that_need_a_claude_stay_404_for_an_api_tab(client):
    for path in ("/sessions/{}/restart", "/sessions/{}/account", "/sessions/{}/fork"):
        assert client.post(path.format(TAB_ID), json={}).status_code == 404
    assert client.patch(f"/sessions/{TAB_ID}", json={"title": "x"}).status_code == 404
    assert client.delete(f"/sessions/{TAB_ID}").status_code == 404


# --- the replay and the subscription ---

def _sample(api_env) -> None:
    append(api_env.record, user_row("u1", "look it up"), tool_use_row("a1", "m1", "t1"), tool_result_row("u2", "t1"),
           assistant_row("a2", "m2", "found it", usage={"input_tokens": 9}),
           partial=json.dumps(user_row("u3", "never shown"))[:30])


def test_the_replay_gives_the_four_rows_and_not_the_row_being_written(api_env):
    _sample(api_env)
    frames = us._replay_frames(TAB_ID, None)
    types = [f["ev"]["type"] for f in frames if f["ch"] == "jsonl"]
    assert types == ["user_message", "assistant", "user", "assistant", "result", "prompt_state"]
    assert all(f["ev"]["sid"] == TAB_ID for f in frames)
    assert "never shown" not in json.dumps(frames)


def test_the_history_get_reads_the_same_record(api_env):
    _sample(api_env)
    body = jsonl_routes.get_chat_history(TAB_ID, None, None)
    assert [event["type"] for event in body["events"]] == ["user_message", "assistant", "user", "assistant", "result"]
    assert body["pos"] == api_env.record.stat().st_size - len(json.dumps(user_row("u3", "never shown"))[:30])


def test_a_conversation_that_has_no_record_yet_replays_as_empty(api_env):
    assert [f["ev"]["type"] for f in us._replay_frames(TAB_ID, None) if f["ch"] == "jsonl"] == ["prompt_state"]
    assert jsonl_routes.get_chat_history(TAB_ID, None, None)["events"] == []


def test_a_subscription_query_with_an_api_tab_id_is_not_dropped_and_its_replay_arrives(api_env):
    from starlette.requests import Request

    _sample(api_env)

    async def scenario():
        scope = {"type": "http", "method": "GET", "path": "/stream/unified", "headers": [],
                 "query_string": f"conn=c-api&jsonl={TAB_ID},api_nobody:5".encode()}
        response = await us.stream_unified(Request(scope))
        generator = response.body_iterator
        frames = [json.loads((await asyncio.wait_for(generator.__anext__(), 2.5))[len("data: "):]) for _ in range(7)]
        conn = us._conns["c-api"]
        subscribed = conn.jsonl_sids
        await generator.aclose()
        return frames, subscribed

    frames, subscribed = run(scenario())
    assert subscribed == {TAB_ID}                               # the unknown API id is dropped, this one is kept
    assert [f["ev"]["type"] for f in frames if f["ch"] == "jsonl"][:2] == ["user_message", "assistant"]


def test_the_upstream_op_jsonl_subscribes_an_api_tab_and_replays_it(api_env):
    _sample(api_env)

    async def scenario():
        conn = us.UnifiedConn(conn_id="c-op")
        us._conns["c-op"] = conn
        try:
            reply = await us.stream_unified_control("c-op", {"op": "jsonl", "sids": [{"sid": TAB_ID, "from": None}]})
            queued = []
            while not conn.queue.empty():
                queued.append(conn.queue.get_nowait())
            return reply, queued
        finally:
            us._conns.pop("c-op", None)

    reply, queued = run(scenario())
    assert reply == {"ok": True, "subscribed": [TAB_ID]}
    assert [f["ev"]["type"] for f in queued][:2] == ["user_message", "assistant"]


def test_a_live_row_reaches_the_subscribed_connection(api_env):
    append(api_env.record, user_row("u0", "before"))

    async def scenario():
        conn = us.UnifiedConn(conn_id="c-live")
        conn.jsonl_sids = {TAB_ID}
        generator = us._unified_gen(conn, initial_view=None)
        try:
            for _ in range(8):                                  # hello, replay, prompt_state, status, overview
                payload = json.loads((await asyncio.wait_for(generator.__anext__(), 2.5))[len("data: "):])
                if payload.get("ch") == "overview":
                    break
            task = asyncio.create_task(stream.run())
            try:
                await asyncio.sleep(0.6)
                append(api_env.record, user_row("u1", "hello"))
                while True:
                    payload = json.loads((await asyncio.wait_for(generator.__anext__(), 2.5))[len("data: "):])
                    if payload.get("ch") == "jsonl":
                        return payload
            finally:
                task.cancel()
        finally:
            await generator.aclose()

    payload = run(scenario())
    assert (payload["ev"]["type"], payload["ev"]["uuid"], payload["ev"]["sid"]) == ("user_message", "u1", TAB_ID)


# --- doors that need a Claude Code ---

def test_a_terminal_is_never_started_for_an_api_tab(isolated_state, monkeypatch):
    started: list[str] = []

    async def spy(sid, **_kwargs):
        started.append(sid)
    monkeypatch.setattr("backend.terminal.routes.ensure_pty_session_for", spy)
    claude = _claude_tab(isolated_state)

    async def scenario():
        us._warm_ptys([TAB_ID, claude.id, "ses_unknown"])
        await asyncio.sleep(0.05)                               # the warm-up runs in the background

    run(scenario())
    assert started == [claude.id]                               # `_warm_ptys` narrows to the tabs of `sessions_meta`


def test_ensure_pty_session_for_returns_at_once_for_an_id_it_does_not_know(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("a terminal was started for an id that is not a Claude tab")
    monkeypatch.setattr(session_resolver, "spawn_pty_session", refuse)
    monkeypatch.setattr(session_resolver, "has_tmux_session", refuse)
    monkeypatch.setattr(session_resolver, "resolve_agent_cfg", refuse)
    run(session_resolver.ensure_pty_session_for(TAB_ID))
    run(session_resolver.ensure_pty_session_for("ses_unknown"))
    assert TAB_ID not in session_resolver.pty_sessions


def test_the_language_of_an_api_tab_is_never_set_so_its_answers_are_not_folded(isolated_state, monkeypatch):
    monkeypatch.setattr(state_mod, "configured_language", lambda _dir: "japanese")
    claude = _claude_tab(isolated_state)
    assert state_mod.session_language(claude.id) == "japanese"
    assert state_mod.session_language(TAB_ID) == ""


@pytest.mark.parametrize("receiver", [TAB_ID, "Support bot"])
def test_a_message_to_an_api_tab_is_refused_with_its_own_code_by_id_or_by_title(receiver):
    with pytest.raises(HTTPException) as refused:
        agent_messages.resolve_receiver(receiver)
    assert refused.value.status_code == 409 and refused.value.detail["code"] == "agent_message_api_tab"
    assert refused.value.detail["params"]["id"] == TAB_ID


def test_other_receivers_are_resolved_or_refused_as_before(isolated_state):
    claude = _claude_tab(isolated_state)
    assert agent_messages.resolve_receiver(claude.id) == claude.id
    assert agent_messages.resolve_receiver("a Claude tab") == claude.id
    with pytest.raises(HTTPException) as unknown:
        agent_messages.resolve_receiver("api_nobody")
    assert unknown.value.detail["code"] == "agent_message_unknown_receiver"


def test_a_claude_tab_with_the_title_of_an_api_tab_keeps_its_own_messages(isolated_state, monkeypatch):
    monkeypatch.setattr(isolated_state, "save_sessions_meta", lambda: None)
    twin = isolated_state.register_session("agent_a", title="Support bot")
    assert agent_messages.resolve_receiver("Support bot") == twin.id


# --- the table is read once for every door ---

def test_a_configuration_read_again_changes_every_door_at_once(client, api_env):
    assert TAB_ID in client.get("/sessions/overview").json()
    write_config(api_env, api_tabs={})
    assert TAB_ID not in client.get("/sessions/overview").json()
    assert [row["id"] for row in client.get("/sessions").json()] == []
