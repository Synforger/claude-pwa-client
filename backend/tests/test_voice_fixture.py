"""e2e 用の、 音声合成の engine の fixture (= `backend/routes/debug_e2e.py`)。

本番の build にも router は載る。 見るのは、 e2e の時だけ・同じ機械の中からだけ返ることと、 返す物が
声の口 (= `backend/routes/voice.py`) の期待する形であること。
"""
from __future__ import annotations

import io
import wave

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from backend.routes import debug_e2e


def _client(peer: str = "127.0.0.1") -> TestClient:
    app = FastAPI()
    app.include_router(debug_e2e.fixture_router)
    return TestClient(app, base_url="http://127.0.0.1:18765", client=(peer, 50000))


@pytest.fixture
def e2e(monkeypatch):
    monkeypatch.setenv("CPC_E2E", "1")


def test_the_fixture_engine_answers_a_query_and_returns_a_sound(e2e):
    client = _client()
    query = client.post("/ext/fixture-voice/audio_query", params={"speaker": 1, "text": "できたよ。"})
    assert query.status_code == 200
    assert query.json()["kana"] == "できたよ。" and "speedScale" in query.json()
    sound = client.post("/ext/fixture-voice/synthesis", params={"speaker": 1}, json=query.json())
    assert sound.status_code == 200 and sound.headers["content-type"] == "audio/wav"
    with wave.open(io.BytesIO(sound.content)) as w:
        assert w.getnframes() > 0


def test_the_fixture_engine_refuses_a_sentence_marked_to_fail(e2e):
    client = _client()
    query = client.post("/ext/fixture-voice/audio_query", params={"speaker": 1, "text": "[fail] no"}).json()
    assert client.post("/ext/fixture-voice/synthesis", params={"speaker": 1}, json=query).status_code == 500


def test_the_fixture_engine_is_not_there_outside_e2e(monkeypatch):
    monkeypatch.delenv("CPC_E2E", raising=False)
    client = _client()
    assert client.post("/ext/fixture-voice/audio_query", params={"speaker": 1, "text": "x"}).status_code == 404
    assert client.post("/ext/fixture-voice/synthesis", params={"speaker": 1}, json={}).status_code == 404


def test_the_fixture_engine_answers_only_from_this_machine(e2e):
    client = _client(peer="100.64.0.9")
    assert client.post("/ext/fixture-voice/audio_query", params={"speaker": 1, "text": "x"}).status_code == 403
