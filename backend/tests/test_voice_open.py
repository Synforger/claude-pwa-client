"""声で聞いている印は、 そのタブの会話がどこかで開いている間に、 人の送信の口で backend が付ける。

会話が開いている = どれかの画面が 🔊 か 🎙 を入れている (= 統合 stream の op=voice で宣言) か、 app の通話がつながって
いる。 打った画面の 🔊 が切れていても、 別の画面や app の通話で開いていれば付く。 別のタブからの連絡と自動の入れ替えは
印の無い口を直に使い、 会話が開いている間は UserPromptSubmit の hook がその事を 1 行で agent へ伝える。
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.routes.agent_messages as agent_messages
import backend.routes.rollover as rollover_routes
import backend.rollover.rollover as rollover
import backend.routes.unified_stream as us
import backend.terminal.routes as routes
from backend._common import state
from backend.speech.speech import VOICE_OPEN_CONTEXT
from backend.routes import hooks as hooks_router
from backend.tests.test_hooks_router import fake_agents, fake_bindings  # noqa: F401 (= hook の用意を使い回す)


@pytest.fixture(autouse=True)
def nothing_open(monkeypatch):
    monkeypatch.setattr(state, "voices_by_conn", {})
    monkeypatch.setattr(us, "voices_by_conn", state.voices_by_conn)
    monkeypatch.setattr(state, "calls_by_conn", {})
    us._conns.clear()
    yield
    us._conns.clear()


def _declare(conn_id: str, sids: list[str]) -> dict:
    us._conns.setdefault(conn_id, us.UnifiedConn(conn_id=conn_id))
    return asyncio.run(us.stream_unified_control(conn_id, {"op": "voice", "sids": sids}))


# --- どこで開いているか ----------------------------------------------------------------------------------------

def test_a_screen_that_declares_the_tab_opens_it_until_it_declares_none():
    assert not state.is_voice_open("ses_a")
    assert _declare("screen-1", ["ses_a"]) == {"ok": True, "voice": ["ses_a"]}
    assert state.is_voice_open("ses_a")
    assert not state.is_voice_open("ses_b")
    _declare("screen-1", [])
    assert not state.is_voice_open("ses_a")


def test_another_screen_keeps_the_tab_open():
    _declare("mac", ["ses_a"])
    _declare("iphone", [])
    assert state.is_voice_open("ses_a")


def test_a_connected_app_call_opens_the_tab_without_a_screen():
    state.calls_by_conn["pc-1"] = "ses_a"
    assert state.is_voice_open("ses_a")
    del state.calls_by_conn["pc-1"]
    assert not state.is_voice_open("ses_a")


# --- 人の送信の口 ---------------------------------------------------------------------------------------------

@pytest.fixture
def sent(monkeypatch) -> list[dict]:
    """人の送信の口が中身の口 (= pty_send) へ渡した payload。"""
    got: list[dict] = []

    async def fake_pty_send(session_id, payload, idempotency_key=None):
        got.append(payload)
        return {"ok": True}

    monkeypatch.setattr(routes, "pty_send", fake_pty_send)
    return got


def _send_from_person(payload: dict) -> None:
    asyncio.run(routes.pty_send_from_person("ses_a", payload, None))


def test_typed_text_is_marked_while_any_screen_has_the_conversation_open(sent):
    _declare("mac", ["ses_a"])
    _send_from_person({"text": "会社の更新を取り込んで", "enter": True})
    assert sent[-1]["text"] == "[voice] 会社の更新を取り込んで"


def test_typed_text_is_marked_while_the_app_call_is_connected(sent):
    state.calls_by_conn["pc-1"] = "ses_a"
    _send_from_person({"text": "聞こえる？", "enter": True})
    assert sent[-1]["text"] == "[voice] 聞こえる？"


def test_typed_text_is_left_alone_while_nothing_is_open(sent):
    _send_from_person({"text": "いつでも入れといて", "enter": True})
    assert sent[-1]["text"] == "いつでも入れといて"


def test_marked_special_and_unsent_text_is_left_alone(sent):
    _declare("mac", ["ses_a"])
    for text in ("[voice] もう付いている", "/compact", "! ls", "# 覚えておいて"):
        _send_from_person({"text": text, "enter": True})
        assert sent[-1]["text"] == text
    _send_from_person({"text": "3", "enter": False})
    assert sent[-1]["text"] == "3"
    _send_from_person({"key": "Escape"})
    assert "text" not in sent[-1]


def test_messages_from_other_tabs_and_the_rollover_use_the_unmarked_door():
    assert agent_messages.pty_send is routes.pty_send
    assert rollover.pty_send is routes.pty_send
    assert rollover_routes.pty_send is routes.pty_send


def test_a_photo_sent_without_text_is_marked_during_a_call(monkeypatch):
    state.calls_by_conn["pc-1"] = "ses_a"
    bodies: list[str] = []

    async def fake_send_body(session_id, text, key=None):
        bodies.append(text)
        return {"ok": True}

    async def ready(_sid):
        return True

    async def saved(_files, _sid):
        return [{"name": "photo.jpg", "path": "/tmp/uploads/photo.jpg"}]

    async def not_launched(_sid, _text):
        return None

    monkeypatch.setattr(routes, "_require_session", lambda _sid: None)
    monkeypatch.setattr(routes, "wait_ready", ready)
    monkeypatch.setattr(routes, "save_to_tmp", saved)
    monkeypatch.setattr(routes, "launch_with_first_message", not_launched)
    monkeypatch.setattr(routes, "_send_body", fake_send_body)
    asyncio.run(routes.pty_send_with_files("ses_a", text="", files=[], idempotency_key=None))
    assert bodies == ["[voice] [添付ファイル: /tmp/uploads/photo.jpg]"]


# --- 人の発話でない turn ---------------------------------------------------------------------------------------

def _prompt_submit(client: TestClient, prompt: str, cwd: str, reply: str | None = None):
    payload = {"hook_event_name": "UserPromptSubmit", "session_id": "claude-uuid", "cwd": cwd, "prompt": prompt}
    return client.post("/hooks/event" + (f"?reply={reply}" if reply else ""), json=payload)


@pytest.fixture
def hook_client(fake_agents, fake_bindings, monkeypatch):  # noqa: F811
    fake_bindings("ses_a", "claude-uuid")
    monkeypatch.setattr(hooks_router.rollover, "turn_started", lambda _sid: None)
    app = FastAPI()
    app.include_router(hooks_router.router)
    return TestClient(app), fake_agents["cwd"]


def test_a_turn_that_is_not_the_person_hears_that_the_conversation_is_open(hook_client):
    client, cwd = hook_client
    _declare("mac", ["ses_a"])
    response = _prompt_submit(client, "Another Claude session sent a message: ...", cwd)
    assert response.json()["context"] == VOICE_OPEN_CONTEXT
    text = _prompt_submit(client, "Another Claude session sent a message: ...", cwd, reply="text")
    assert text.text == VOICE_OPEN_CONTEXT


def test_the_person_s_marked_turn_and_a_closed_conversation_get_no_line(hook_client):
    client, cwd = hook_client
    _declare("mac", ["ses_a"])
    assert "context" not in _prompt_submit(client, "[voice] 明日の予定は", cwd).json()
    _declare("mac", [])
    assert "context" not in _prompt_submit(client, "Another Claude session sent a message: ...", cwd).json()
    assert _prompt_submit(client, "Another Claude session sent a message: ...", cwd, reply="text").text == ""
