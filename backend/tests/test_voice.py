"""声の口 (= `backend/routes/voice.py`)。

音声合成の engine は立てない。 engine を呼ぶ 1 か所 (= `_call_engine`) を差し替えて、 この口が決める事
(= 設定の読み方 / どのタブが声を持つか / engine へ渡す値 / 失敗の返し方) だけを見る。
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import backend.config as config_mod
from backend._generated import http_endpoints as http
from backend.routes import voice
from backend.state import SessionDef

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt "
VOICE = {
    "engine": "http://127.0.0.1:10101/",
    "speaker": 100,
    "query": {"prePhonemeLength": 0.05},
    "marks": {
        "calm": {"speedScale": 1.1, "pitchScale": -0.06},
        "happy": {"speedScale": 1.15, "tempoDynamicsScale": 1.3},
        "sleepy": {"speaker": 103, "intonationScale": 1.2},
    },
    "default": "calm",
}
# engine が返す AudioQuery の見本 (= 上書きできる key はここに在る物だけ)。
QUERY = {"accent_phrases": [], "speedScale": 1.0, "pitchScale": 0.0, "intonationScale": 1.0,
         "tempoDynamicsScale": 1.0, "prePhonemeLength": 0.1, "kana": ""}


def _config(monkeypatch, tmp_path, **agents) -> None:
    """設定 file を書いて読み口を向け直す (= conftest の後始末が cache を消せる形)。"""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"agents": agents}))
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)
    config_mod.get_config.cache_clear()


@pytest.fixture
def tabs(isolated_state, monkeypatch, tmp_path):
    """声を持つ agent のタブ (= ses_voice) と、 持たない agent のタブ (= ses_plain)。"""
    _config(monkeypatch, tmp_path, speaker={"voice": VOICE}, quiet={})
    meta = isolated_state.sessions_meta
    meta["ses_voice"] = SessionDef(id="ses_voice", agent_id="speaker", title="talk", created_at=0)
    meta["ses_plain"] = SessionDef(id="ses_plain", agent_id="quiet", title="work", created_at=0)
    return meta


@pytest.fixture
def engine(monkeypatch) -> list[tuple[str, dict | None]]:
    """engine へ届いた呼び出しの記録。 engine は、 問い合わせに見本を、 合成に音を返す。"""
    calls: list[tuple[str, dict | None]] = []

    def fake(url, body, timeout):
        calls.append((url, body))
        if "/audio_query" in url:
            return 200, "application/json", json.dumps(QUERY).encode()
        return 200, "audio/wav", WAV

    monkeypatch.setattr(voice, "_call_engine", fake)
    return calls


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(voice.router)
    return TestClient(app)


def _code(response) -> str:
    return response.json()["detail"]["code"]


# --- どのタブが声を持つか ---------------------------------------------------------

def test_a_tab_of_an_agent_with_a_voice_says_so_and_names_its_marks(client, tabs):
    assert client.get("/sessions/ses_voice/voice").json() == {
        "enabled": True, "marks": ["calm", "happy", "sleepy"], "default": "calm"}


def test_a_tab_of_an_agent_with_no_voice_says_so(client, tabs):
    assert client.get("/sessions/ses_plain/voice").json() == {"enabled": False, "marks": [], "default": ""}


def test_a_tab_that_does_not_exist_is_not_found(client, tabs, engine):
    assert _code(client.get("/sessions/ses_gone/voice")) == "voice_unknown_session"
    assert _code(client.post("/sessions/ses_gone/voice/utterances", json={"text": "やあ。"})) == "voice_unknown_session"
    assert _code(client.post("/sessions/ses_gone/voice/synthesis", json={"text": "やあ。"})) == "voice_unknown_session"
    assert engine == []


def test_a_tab_with_no_voice_takes_no_speech(client, tabs, engine):
    r = client.post("/sessions/ses_plain/voice/utterances", json={"text": "やあ。"})
    assert (r.status_code, _code(r)) == (409, "voice_not_enabled")
    r = client.post("/sessions/ses_plain/voice/synthesis", json={"text": "やあ。"})
    assert (r.status_code, _code(r)) == (409, "voice_not_enabled")
    assert engine == []


def test_the_answers_have_the_declared_shape(client, tabs):
    """宣言 (= contracts/schema/http-endpoints.yaml) から作った型に、 実際の応答が通る。"""
    http.GetSessionsSidVoiceResponse.model_validate(client.get("/sessions/ses_voice/voice").json())
    http.GetSessionsSidVoiceResponse.model_validate(client.get("/sessions/ses_plain/voice").json())
    body = {"text": "[happy] できたよ！"}
    http.PostSessionsSidVoiceUtterancesRequest.model_validate(body)
    said = http.PostSessionsSidVoiceUtterancesResponse.model_validate(
        client.post("/sessions/ses_voice/voice/utterances", json=body).json())
    assert said.utterances == [{"mark": "happy", "text": "できたよ！"}]
    http.PostSessionsSidVoiceSynthesisRequest.model_validate({"text": "できたよ！", "mark": "happy"})
    http.PostSessionsSidVoiceSynthesisRequest.model_validate({"text": "できたよ！"})


# --- 設定の読み方 ----------------------------------------------------------------

@pytest.mark.parametrize("broken", [
    None, "on", [],
    {**VOICE, "engine": "ftp://host"},
    {**VOICE, "engine": 10101},
    {**VOICE, "speaker": "100"},
    {**VOICE, "speaker": True},
    {**VOICE, "query": {"speedScale": "fast"}},
    {**VOICE, "marks": {"calm": {"speedScale": "fast"}}},
    {**VOICE, "marks": {"not a name": {}}},
    {**VOICE, "marks": ["calm"]},
    {**VOICE, "default": "angry"},
    {**VOICE, "default": ["calm"]},
    {"engine": "http://127.0.0.1:10101", "speaker": 1, "default": "calm"},
])
def test_a_voice_setting_of_the_wrong_shape_counts_as_no_voice(broken):
    assert voice.voice_settings(broken) is None


def test_marks_and_the_base_query_may_be_left_out():
    settings = voice.voice_settings({"engine": "http://127.0.0.1:10101", "speaker": 1})
    assert settings == {"engine": "http://127.0.0.1:10101", "speaker": 1, "query": {}, "marks": {}, "default": ""}


def test_the_default_mark_is_the_first_one_when_none_is_named():
    settings = voice.voice_settings({k: v for k, v in VOICE.items() if k != "default"})
    assert settings["default"] == "calm"


# --- 声にする文 ------------------------------------------------------------------

def test_a_reply_comes_back_as_the_sentences_to_say(client, tabs):
    r = client.post("/sessions/ses_voice/voice/utterances",
                    json={"text": "[happy] できたよ！\n場所は `~/a.md` だよ。\n```\ncode\n```"})
    assert r.status_code == 200
    assert r.json() == {"utterances": [
        {"mark": "happy", "text": "できたよ！"}, {"mark": "calm", "text": "場所は だよ。"}]}


def test_a_reply_with_nothing_to_say_comes_back_empty(client, tabs):
    assert client.post("/sessions/ses_voice/voice/utterances", json={"text": "```\ncode\n```"}).json() == {"utterances": []}


def test_a_reply_too_long_to_cut_is_refused_whole(client, tabs):
    r = client.post("/sessions/ses_voice/voice/utterances", json={"text": "あ" * (voice.MAX_REPLY_CHARS + 1)})
    assert (r.status_code, _code(r)) == (413, "voice_text_too_long")


@pytest.mark.parametrize("body", [{}, {"text": 5}, {"text": None}])
def test_a_request_with_no_text_is_refused(client, tabs, engine, body):
    assert _code(client.post("/sessions/ses_voice/voice/utterances", json=body)) == "voice_bad_request"
    assert _code(client.post("/sessions/ses_voice/voice/synthesis", json=body)) == "voice_bad_request"
    assert engine == []


# --- 音にする --------------------------------------------------------------------

def test_a_sentence_is_asked_of_the_engine_and_comes_back_as_sound(client, tabs, engine):
    r = client.post("/sessions/ses_voice/voice/synthesis", json={"text": "できたよ。", "mark": "happy"})
    assert r.status_code == 200
    assert r.content == WAV
    assert r.headers["content-type"] == "audio/wav"
    assert r.headers["cache-control"] == "no-store"
    (query_url, query_body), (synth_url, synth_body) = engine
    assert query_url == "http://127.0.0.1:10101/audio_query?speaker=100&text=%E3%81%A7%E3%81%8D%E3%81%9F%E3%82%88%E3%80%82"
    assert query_body is None
    assert synth_url == "http://127.0.0.1:10101/synthesis?speaker=100"
    # 見本の値に、 共通の値 (= query) を当て、 その上に印の値を当てる。 印が触らない値は共通か見本のまま。
    assert synth_body == {**QUERY, "prePhonemeLength": 0.05, "speedScale": 1.15, "tempoDynamicsScale": 1.3}


def test_a_sentence_with_no_mark_is_said_the_default_way(client, tabs, engine):
    client.post("/sessions/ses_voice/voice/synthesis", json={"text": "うん。"})
    assert engine[1][1] == {**QUERY, "prePhonemeLength": 0.05, "speedScale": 1.1, "pitchScale": -0.06}


def test_a_mark_may_name_another_style_of_the_voice(client, tabs, engine):
    client.post("/sessions/ses_voice/voice/synthesis", json={"text": "ねむい…。", "mark": "sleepy"})
    (query_url, _), (synth_url, synth_body) = engine
    assert "speaker=103" in query_url and synth_url.endswith("speaker=103")
    assert synth_body == {**QUERY, "prePhonemeLength": 0.05, "intonationScale": 1.2}  # speaker は query の値ではない


def test_a_value_the_engine_does_not_have_is_not_sent(client, tabs, engine, monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path, speaker={"voice": {**VOICE, "query": {"madeUpScale": 2.0}}})
    client.post("/sessions/ses_voice/voice/synthesis", json={"text": "うん。"})
    assert "madeUpScale" not in engine[1][1]


def test_a_mark_the_agent_does_not_have_is_refused(client, tabs, engine):
    r = client.post("/sessions/ses_voice/voice/synthesis", json={"text": "うん。", "mark": "angry"})
    assert (r.status_code, _code(r)) == (400, "voice_unknown_mark")
    assert engine == []


def test_a_mark_that_is_no_name_is_refused(client, tabs, engine):
    r = client.post("/sessions/ses_voice/voice/synthesis", json={"text": "うん。", "mark": 3})
    assert (r.status_code, _code(r)) == (400, "voice_bad_request")
    assert engine == []


@pytest.mark.parametrize("text", ["", "   ", "…。"])
def test_a_sentence_with_nothing_to_say_is_refused(client, tabs, engine, text):
    r = client.post("/sessions/ses_voice/voice/synthesis", json={"text": text})
    assert (r.status_code, _code(r)) == (400, "voice_nothing_to_say")
    assert engine == []


def test_a_sentence_too_long_for_one_breath_is_refused(client, tabs, engine):
    r = client.post("/sessions/ses_voice/voice/synthesis", json={"text": "あ" * (voice.MAX_UTTERANCE_CHARS + 1)})
    assert (r.status_code, _code(r)) == (413, "voice_text_too_long")
    assert engine == []


def test_an_engine_that_is_not_running_says_so(client, tabs, monkeypatch):
    def down(url, body, timeout):
        raise OSError("connection refused")
    monkeypatch.setattr(voice, "_call_engine", down)
    r = client.post("/sessions/ses_voice/voice/synthesis", json={"text": "うん。"})
    assert (r.status_code, _code(r)) == (502, "voice_engine_unreachable")


@pytest.mark.parametrize("failing", ["/audio_query", "/synthesis"])
def test_an_engine_that_refuses_says_which_step_and_what_it_answered(client, tabs, monkeypatch, failing):
    def fake(url, body, timeout):
        if failing in url:
            return 422, "application/json", b'{"detail": "no such speaker"}'
        return 200, "application/json", json.dumps(QUERY).encode()
    monkeypatch.setattr(voice, "_call_engine", fake)
    r = client.post("/sessions/ses_voice/voice/synthesis", json={"text": "うん。"})
    assert (r.status_code, _code(r)) == (502, "voice_engine_failed")
    assert r.json()["detail"]["params"] == {"step": failing.strip("/"), "status": 422}


def test_an_engine_that_answers_something_that_is_no_query_says_so(client, tabs, monkeypatch):
    monkeypatch.setattr(voice, "_call_engine", lambda url, body, timeout: (200, "text/html", b"<html>"))
    r = client.post("/sessions/ses_voice/voice/synthesis", json={"text": "うん。"})
    assert (r.status_code, _code(r)) == (502, "voice_engine_failed")


def test_an_engine_that_answers_something_that_is_no_sound_says_so(client, tabs, monkeypatch):
    def fake(url, body, timeout):
        if "/audio_query" in url:
            return 200, "application/json", json.dumps(QUERY).encode()
        return 200, "application/json", b'{"detail": "busy"}'
    monkeypatch.setattr(voice, "_call_engine", fake)
    r = client.post("/sessions/ses_voice/voice/synthesis", json={"text": "うん。"})
    assert (r.status_code, _code(r)) == (502, "voice_engine_failed")
    assert r.json()["detail"]["params"] == {"step": "synthesis", "status": 200}


def test_a_setting_of_the_wrong_shape_is_logged_once(client, tabs, monkeypatch, tmp_path, caplog):
    _config(monkeypatch, tmp_path, speaker={"voice": {**VOICE, "speaker": "100"}})
    monkeypatch.setattr(voice, "_warned", set())
    with caplog.at_level("WARNING", logger=voice.logger.name):
        assert client.get("/sessions/ses_voice/voice").json()["enabled"] is False
        assert client.get("/sessions/ses_voice/voice").json()["enabled"] is False
    assert [r.getMessage() for r in caplog.records].count(
        "voice: agent=speaker has a voice setting of the wrong shape; it has no voice") == 1
