"""声の口 (= `backend/routes/voice.py`)。

音声合成の engine は立てない。 engine を呼ぶ 1 か所 (= `_call_engine`) を差し替えて、 この口が決める事
(= 設定の読み方 / どのタブが声を持つか / engine へ渡す値 / 失敗の返し方) だけを見る。
"""
from __future__ import annotations

import http.client
import json
import os

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import backend.config as config_mod
from backend._generated import http_endpoints as declared
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
LISTEN = {"engine": "http://127.0.0.1:10102/", "prompt": "Claude、PWA。"}
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
    """声を持つ agent のタブ (= ses_voice)、 声を聞き取りもする agent のタブ (= ses_listen)、 声を持たない agent の
    タブ (= ses_plain)。"""
    _config(monkeypatch, tmp_path, speaker={"voice": VOICE}, quiet={}, listener={"voice": {**VOICE, "listen": LISTEN}})
    meta = isolated_state.sessions_meta
    meta["ses_listen"] = SessionDef(id="ses_listen", agent_id="listener", title="hear", created_at=0)
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
        "enabled": True, "marks": ["calm", "happy", "sleepy", "mute"], "default": "calm", "listen": False, "turn": False,
        "conversation": voice.CONVERSATION_DEFAULTS, "tuning_error": ""}


def test_a_tab_of_an_agent_with_no_voice_says_so(client, tabs):
    assert client.get("/sessions/ses_plain/voice").json() == {
        "enabled": False, "marks": [], "default": "", "listen": False, "turn": False,
        "conversation": None, "tuning_error": ""}


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
    declared.GetSessionsSidVoiceResponse.model_validate(client.get("/sessions/ses_voice/voice").json())
    declared.GetSessionsSidVoiceResponse.model_validate(client.get("/sessions/ses_plain/voice").json())
    body = {"text": "[happy] できたよ！"}
    declared.PostSessionsSidVoiceUtterancesRequest.model_validate(body)
    said = declared.PostSessionsSidVoiceUtterancesResponse.model_validate(
        client.post("/sessions/ses_voice/voice/utterances", json=body).json())
    assert said.utterances == [{"mark": "happy", "text": "できたよ！", "values": {}}]
    declared.PostSessionsSidVoiceSynthesisRequest.model_validate({"text": "できたよ！", "mark": "happy"})
    declared.PostSessionsSidVoiceSynthesisRequest.model_validate({"text": "できたよ！"})


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
    {**VOICE, "listen": "on"},
    {**VOICE, "listen": {}},
    {**VOICE, "listen": {"engine": "ws://127.0.0.1:10102"}},
    {**VOICE, "listen": {"engine": "http://127.0.0.1:10102", "prompt": ["Claude"]}},
    {**VOICE, "listen": {"engine": "http://127.0.0.1:10102", "turn": 1}},
    {**VOICE, "conversation": "slow"},
    {**VOICE, "conversation": {"pause": 700}},
    {**VOICE, "conversation": {"pause_ms": 0}},
    {**VOICE, "conversation": {"pause_ms": 0.7}},
    {**VOICE, "conversation": {"pause_ms": 3000, "wait_ms": 3000}},
    {**VOICE, "conversation": {"unfinished_endings": "、"}},
    {**VOICE, "conversation": {"unfinished_endings": ["、", " "]}},
    {**VOICE, "conversation": {"interrupt": "yes"}},
    {**VOICE, "tuning": ["voice.json"]},
    {**VOICE, "compressor": "on"},
    {**VOICE, "compressor": {"threshold": -18}},
    {**VOICE, "compressor": {"ratio": 30}},
    {**VOICE, "compressor": {"limit_db": 1}},
    {**VOICE, "compressor": {"makeup_db": "6"}},
])
def test_a_voice_setting_of_the_wrong_shape_counts_as_no_voice(broken):
    assert voice.voice_settings(broken) is None


def test_marks_and_the_base_query_may_be_left_out():
    settings = voice.voice_settings({"engine": "http://127.0.0.1:10101", "speaker": 1})
    assert settings == {"engine": "http://127.0.0.1:10101", "speaker": 1, "query": {}, "marks": {}, "default": "",
                        "listen": None, "conversation": voice.CONVERSATION_DEFAULTS, "compressor": None, "tuning": ""}


def test_the_conversation_takes_the_defaults_for_what_is_not_written():
    settings = voice.voice_settings({**VOICE, "conversation": {"pause_ms": 900, "interrupt": False}})
    assert settings["conversation"] == {**voice.CONVERSATION_DEFAULTS, "pause_ms": 900, "interrupt": False}


def test_the_default_mark_is_the_first_one_when_none_is_named():
    settings = voice.voice_settings({k: v for k, v in VOICE.items() if k != "default"})
    assert settings["default"] == "calm"


# --- 声にする文 ------------------------------------------------------------------

def test_a_reply_comes_back_as_the_sentences_to_say(client, tabs):
    r = client.post("/sessions/ses_voice/voice/utterances",
                    json={"text": "[happy] できたよ！\n場所は `~/a.md` だよ。\n```\ncode\n```"})
    assert r.status_code == 200
    assert r.json() == {"utterances": [
        {"mark": "happy", "text": "できたよ！", "values": {}}, {"mark": "calm", "text": "場所は だよ。", "values": {}}]}


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
    # 文の前の無音は、 速さを掛けて渡す (= 書いた 0.05 秒のまま空く)
    assert synth_body == {**QUERY, "prePhonemeLength": pytest.approx(0.05 * 1.15), "speedScale": 1.15,
                          "tempoDynamicsScale": 1.3}


def test_the_pauses_around_a_sentence_stay_as_written_whatever_the_speed(client, tabs, engine, monkeypatch, tmp_path):
    """engine は前後の無音も speedScale で縮めるので、 速さを掛けて渡す。"""
    _config(monkeypatch, tmp_path, speaker={"voice": {
        **VOICE, "query": {"prePhonemeLength": 0.05}, "marks": {"fast": {"speedScale": 2.0}, "plain": {}},
        "default": "plain"}})
    r = client.post("/sessions/ses_voice/voice/synthesis", json={"text": "やあ。", "mark": "fast"})
    assert r.status_code == 200, r.text
    assert engine[-1][1]["prePhonemeLength"] == pytest.approx(0.1)
    client.post("/sessions/ses_voice/voice/synthesis", json={"text": "やあ。", "mark": "plain"})
    assert engine[-1][1]["prePhonemeLength"] == pytest.approx(0.05)


def test_the_compressor_is_put_on_each_sentence_when_written(client, tabs, engine, monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path, speaker={"voice": {**VOICE, "compressor": {"ratio": 3}}})
    seen = []

    async def fake(sound, settings):
        seen.append((sound, settings))
        return b"RIFF-compressed"

    monkeypatch.setattr(voice, "compress", fake)
    r = client.post("/sessions/ses_voice/voice/synthesis", json={"text": "やあ。"})
    assert (r.content, seen) == (b"RIFF-compressed", [(WAV, {"ratio": 3})])


def test_no_compressor_is_put_on_when_none_is_written(client, tabs, engine, monkeypatch):
    async def fake(sound, settings):
        raise AssertionError("not to be called")

    monkeypatch.setattr(voice, "compress", fake)
    assert client.post("/sessions/ses_voice/voice/synthesis", json={"text": "やあ。"}).content == WAV


def test_a_compressor_that_fails_leaves_the_engine_sound_and_says_why_once(client, tabs, engine, monkeypatch,
                                                                           tmp_path, caplog):
    _config(monkeypatch, tmp_path, speaker={"voice": {**VOICE, "compressor": {}}})
    monkeypatch.setattr(voice, "_compressor_logged", set())

    async def broken(sound, settings):
        raise voice.CompressorError("ffmpeg is not on PATH")

    monkeypatch.setattr(voice, "compress", broken)
    with caplog.at_level("WARNING", logger=voice.logger.name):
        for _ in range(2):
            assert client.post("/sessions/ses_voice/voice/synthesis", json={"text": "やあ。"}).content == WAV
    assert sum("compressor was skipped" in r.getMessage() for r in caplog.records) == 1


def test_a_pause_the_engine_does_not_have_is_not_sent(client, tabs, engine, monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path, speaker={"voice": {**VOICE, "query": {"postPhonemeLength": 0.45},
                                                      "marks": {"fast": {"speedScale": 2.0}}, "default": "fast"}})
    client.post("/sessions/ses_voice/voice/synthesis", json={"text": "やあ。", "mark": "fast"})
    assert "postPhonemeLength" not in engine[-1][1]


def test_a_sentence_with_no_mark_is_said_the_default_way(client, tabs, engine):
    client.post("/sessions/ses_voice/voice/synthesis", json={"text": "うん。"})
    assert engine[1][1] == {**QUERY, "prePhonemeLength": pytest.approx(0.05 * 1.1), "speedScale": 1.1, "pitchScale": -0.06}


def test_a_mark_may_name_another_style_of_the_voice(client, tabs, engine):
    client.post("/sessions/ses_voice/voice/synthesis", json={"text": "ねむい…。", "mark": "sleepy"})
    (query_url, _), (synth_url, synth_body) = engine
    assert "speaker=103" in query_url and synth_url.endswith("speaker=103")
    assert synth_body == {**QUERY, "prePhonemeLength": 0.05, "intonationScale": 1.2}  # speaker は query の値ではない


def test_a_mark_with_values_comes_back_with_them(client, tabs, caplog):
    with caplog.at_level("INFO", logger=voice.logger.name):
        r = client.post("/sessions/ses_voice/voice/utterances", json={"text": "[happy i=1.4 s=3] やった！"})
    assert r.json() == {"utterances": [{"mark": "happy", "text": "やった！", "values": {"intonationScale": 1.4}}]}
    assert any("not used: s=3" in rec.getMessage() for rec in caplog.records)


def test_values_go_over_the_values_of_the_mark(client, tabs, engine):
    client.post("/sessions/ses_voice/voice/synthesis",
                json={"text": "やった！", "mark": "happy", "values": {"intonationScale": 1.4, "speedScale": 1.3}})
    assert engine[1][1] == {**QUERY, "prePhonemeLength": pytest.approx(0.05 * 1.3), "speedScale": 1.3,
                            "tempoDynamicsScale": 1.3, "intonationScale": 1.4}


def test_a_value_out_of_range_is_said_the_way_of_the_mark(client, tabs, engine, caplog):
    with caplog.at_level("INFO", logger=voice.logger.name):
        r = client.post("/sessions/ses_voice/voice/synthesis",
                        json={"text": "やった！", "mark": "happy", "values": {"speedScale": 5}})
    assert r.status_code == 200
    assert engine[1][1]["speedScale"] == 1.15
    assert any("not used: speedScale=5" in rec.getMessage() for rec in caplog.records)


def test_values_that_are_no_set_are_refused(client, tabs, engine):
    r = client.post("/sessions/ses_voice/voice/synthesis", json={"text": "うん。", "values": [1.2]})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "voice_bad_request"
    assert engine == []


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


@pytest.mark.parametrize("error", [
    OSError("connection refused"), TimeoutError("timed out"), http.client.IncompleteRead(b"RIFF")])
def test_an_engine_that_is_not_running_or_drops_the_answer_says_so(client, tabs, monkeypatch, error):
    def down(url, body, timeout):
        raise error
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


# --- 人の声を聞き取る ------------------------------------------------------------

WEBM = b"\x1aE\xdf\xa3 recorded speech"


@pytest.fixture
def listener(monkeypatch) -> list[dict]:
    """聞き取りの engine へ届いた呼び出しの記録。 engine は、 区切りごとに改行を挟んだ文を返す。"""
    calls: list[dict] = []

    def fake(url, fields, audio, audio_type, timeout):
        calls.append({"url": url, "fields": fields, "audio": audio, "type": audio_type, "timeout": timeout})
        return 200, "application/json", json.dumps({"text": " 明日の予定を教えて。\n よろしく\n"}).encode()

    monkeypatch.setattr(voice, "_call_listener", fake)
    return calls


def _say(client, sid="ses_listen", audio=WEBM, kind="audio/webm;codecs=opus"):
    return client.post(f"/sessions/{sid}/voice/transcription", content=audio, headers={"Content-Type": kind})


def test_a_tab_that_listens_says_so(client, tabs):
    body = client.get("/sessions/ses_listen/voice").json()
    assert body["enabled"] is True
    assert body["listen"] is True
    assert body["turn"] is False


def test_a_tab_with_a_turn_model_says_so(client, tabs, monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path, listener={"voice": {**VOICE, "listen": {**LISTEN, "turn": "/models/turn.onnx"}}})
    assert client.get("/sessions/ses_listen/voice").json()["turn"] is True


def test_what_was_said_comes_back_as_one_line(client, tabs, listener):
    r = _say(client)
    assert r.status_code == 200
    assert r.json() == {"text": "明日の予定を教えて。 よろしく"}
    assert listener == [{"url": "http://127.0.0.1:10102/inference",
                         "fields": {"response_format": "json", "prompt": "Claude、PWA。"},
                         "audio": WEBM, "type": "audio/webm", "timeout": voice.LISTEN_TIMEOUT_SEC}]


def test_no_prompt_is_sent_when_none_is_set(client, tabs, listener, monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path, listener={"voice": {**VOICE, "listen": {"engine": "http://127.0.0.1:10102"}}})
    assert _say(client).status_code == 200
    assert listener[0]["fields"] == {"response_format": "json"}


def test_silence_comes_back_as_an_empty_text(client, tabs, monkeypatch):
    monkeypatch.setattr(voice, "_call_listener", lambda *a: (200, "application/json", b'{"text": "\\n"}'))
    assert _say(client).json() == {"text": ""}


def test_a_tab_that_does_not_listen_takes_no_sound(client, tabs, listener):
    r = _say(client, "ses_voice")
    assert (r.status_code, _code(r)) == (409, "voice_listen_not_enabled")
    r = _say(client, "ses_plain")
    assert (r.status_code, _code(r)) == (409, "voice_not_enabled")
    r = _say(client, "ses_gone")
    assert (r.status_code, _code(r)) == (404, "voice_unknown_session")
    assert listener == []


@pytest.mark.parametrize("audio,kind", [(WEBM, "application/json"), (WEBM, ""), (b"", "audio/mp4")])
def test_a_body_that_is_no_sound_is_refused_before_the_engine(client, tabs, listener, audio, kind):
    r = _say(client, audio=audio, kind=kind)
    assert (r.status_code, _code(r)) == (400, "voice_bad_request")
    assert listener == []


def test_a_sound_over_the_limit_is_refused_before_the_engine(client, tabs, listener):
    r = _say(client, audio=b"\0" * (voice.MAX_AUDIO_BYTES + 1))
    assert (r.status_code, _code(r)) == (413, "voice_audio_too_large")
    assert r.json()["detail"]["params"] == {"limit": voice.MAX_AUDIO_BYTES}
    assert listener == []


def test_a_listening_engine_that_cannot_be_reached_says_so(client, tabs, monkeypatch):
    def down(*_):
        raise ConnectionRefusedError
    monkeypatch.setattr(voice, "_call_listener", down)
    r = _say(client)
    assert (r.status_code, _code(r)) == (502, "voice_listen_unreachable")


@pytest.mark.parametrize("answer", [
    (500, "application/json", b'{"error": "FFmpeg conversion failed."}'),
    (200, "text/html", b"<html>"),
    (200, "application/json", b'{"error": "busy"}'),
])
def test_a_listening_engine_that_fails_says_so(client, tabs, monkeypatch, answer):
    monkeypatch.setattr(voice, "_call_listener", lambda *a: answer)
    r = _say(client)
    assert (r.status_code, _code(r)) == (502, "voice_listen_failed")
    assert r.json()["detail"]["params"] == {"status": answer[0]}


def test_the_listening_answers_have_the_declared_shape(client, tabs, listener):
    declared.GetSessionsSidVoiceResponse.model_validate(client.get("/sessions/ses_listen/voice").json())
    declared.PostSessionsSidVoiceTranscriptionResponse.model_validate(_say(client).json())


def test_the_sound_goes_to_the_engine_as_a_form(monkeypatch):
    """engine へは、 文字の欄と音の `file` を multipart で渡す (= whisper-server の /inference の形)。"""
    sent = {}

    def fake_post(url, data, content_type, timeout):
        sent.update(url=url, data=data, content_type=content_type)
        return 200, "application/json", b'{"text": ""}'
    monkeypatch.setattr(voice, "_post", fake_post)
    voice._call_listener("http://e/inference", {"response_format": "json"}, WEBM, "audio/webm", 1.0)
    boundary = sent["content_type"].split("boundary=")[1]
    assert sent["content_type"].startswith("multipart/form-data; boundary=")
    assert sent["data"] == (
        f'--{boundary}\r\nContent-Disposition: form-data; name="response_format"\r\n\r\njson\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech"\r\n'
        f'Content-Type: audio/webm\r\n\r\n'.encode() + WEBM + f'\r\n--{boundary}--\r\n'.encode())



# --- 言い終えを判定する model と、 会話の持ち主 ---------------------------------------

def test_the_turn_model_file_is_served_as_it_is(client, tabs, monkeypatch, tmp_path):
    model = tmp_path / "turn.onnx"
    model.write_bytes(b"ONNX model bytes")
    _config(monkeypatch, tmp_path, listener={"voice": {**VOICE, "listen": {**LISTEN, "turn": str(model)}}})
    r = client.get("/sessions/ses_listen/voice/turn-model")
    assert r.status_code == 200
    assert r.content == b"ONNX model bytes"
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers.get("etag")


def test_a_turn_model_that_is_not_set_or_not_there_is_not_found(client, tabs, monkeypatch, tmp_path):
    assert _code(client.get("/sessions/ses_listen/voice/turn-model")) == "voice_turn_model_missing"
    _config(monkeypatch, tmp_path, speaker={"voice": VOICE},
            listener={"voice": {**VOICE, "listen": {**LISTEN, "turn": str(tmp_path / "gone.onnx")}}})
    r = client.get("/sessions/ses_listen/voice/turn-model")
    assert (r.status_code, _code(r)) == (404, "voice_turn_model_missing")
    r = client.get("/sessions/ses_voice/voice/turn-model")
    assert (r.status_code, _code(r)) == (409, "voice_listen_not_enabled")


@pytest.fixture
def conversations(monkeypatch):
    held: dict[str, str] = {}
    monkeypatch.setattr(voice, "_conversations", held)
    return held


def _from(client, name, sid="ses_listen"):
    return client.post(f"/sessions/{sid}/voice/transcription", content=WEBM,
                       headers={"Content-Type": "audio/webm", "X-Voice-Conversation": name})


def test_the_screen_that_opened_the_conversation_last_holds_it(client, tabs, listener, conversations):
    assert client.post("/sessions/ses_listen/voice/conversation", json={"client": "mac-1"}).json() == {"client": "mac-1"}
    assert _from(client, "mac-1").status_code == 200
    assert client.post("/sessions/ses_listen/voice/conversation", json={"client": "phone-1"}).status_code == 200
    r = _from(client, "mac-1")
    assert (r.status_code, _code(r)) == (409, "voice_conversation_elsewhere")
    assert _from(client, "phone-1").status_code == 200
    assert len(listener) == 2


def test_a_screen_that_sends_first_after_a_restart_holds_the_conversation(client, tabs, listener, conversations):
    assert _from(client, "mac-1").status_code == 200
    assert conversations == {"ses_listen": "mac-1"}
    assert _code(_from(client, "phone-1")) == "voice_conversation_elsewhere"


def test_only_the_holder_closes_the_conversation(client, tabs, conversations):
    client.post("/sessions/ses_listen/voice/conversation", json={"client": "phone-1"})
    r = client.request("DELETE", "/sessions/ses_listen/voice/conversation", json={"client": "mac-1"})
    assert r.json() == {"closed": False}
    assert conversations == {"ses_listen": "phone-1"}
    r = client.request("DELETE", "/sessions/ses_listen/voice/conversation", json={"client": "phone-1"})
    assert r.json() == {"closed": True}
    assert conversations == {}


@pytest.mark.parametrize("body", [None, {}, {"client": ""}, {"client": "a b"}, {"client": "x" * 65}, {"client": 1}])
def test_a_conversation_needs_a_proper_client_name(client, tabs, conversations, body):
    r = client.post("/sessions/ses_listen/voice/conversation", json=body)
    assert (r.status_code, _code(r)) == (400, "voice_bad_request")
    assert conversations == {}


def test_a_tab_that_does_not_listen_has_no_conversation(client, tabs, conversations):
    r = client.post("/sessions/ses_voice/voice/conversation", json={"client": "mac-1"})
    assert (r.status_code, _code(r)) == (409, "voice_listen_not_enabled")
    r = client.post("/sessions/ses_plain/voice/conversation", json={"client": "mac-1"})
    assert (r.status_code, _code(r)) == (409, "voice_not_enabled")


def test_the_conversation_answers_have_the_declared_shape(client, tabs, conversations):
    body = {"client": "mac-1"}
    declared.PostSessionsSidVoiceConversationRequest.model_validate(body)
    declared.PostSessionsSidVoiceConversationResponse.model_validate(
        client.post("/sessions/ses_listen/voice/conversation", json=body).json())
    declared.DeleteSessionsSidVoiceConversationResponse.model_validate(
        client.request("DELETE", "/sessions/ses_listen/voice/conversation", json=body).json())


# --- 調整の file (= agent が自分の声と間の取り方を書く) ---------------------------------

@pytest.fixture
def tuned(isolated_state, monkeypatch, tmp_path):
    """調整の file を持つ agent のタブ (= ses_tuned)。 返すのは file の path (= まだ書いていない)。"""
    path = tmp_path / "voice.json"
    _config(monkeypatch, tmp_path, tuned={"voice": {**VOICE, "listen": LISTEN, "tuning": str(path)}})
    isolated_state.sessions_meta["ses_tuned"] = SessionDef(id="ses_tuned", agent_id="tuned", title="t", created_at=0)
    monkeypatch.setattr(voice, "_tuning_files", {})
    monkeypatch.setattr(voice, "_tuning_logged", {})
    return path


def _write(path, data) -> None:
    """書き換えを確実に別物と見せる (= 同じ大きさ・同じ時刻の書き換えを cache が見落とさないように)。"""
    text = data if isinstance(data, str) else json.dumps(data)
    before = path.stat().st_mtime_ns if path.exists() else 0
    path.write_text(text)
    os.utime(path, ns=(before + 1_000_000_000, before + 1_000_000_000))


def test_the_tuning_file_is_laid_over_the_setting(client, tuned, engine):
    _write(tuned, {"speaker": 200, "marks": {"calm": {"speedScale": 0.9}}, "default": "calm",
                   "conversation": {"pause_ms": 900}})
    got = client.get("/sessions/ses_tuned/voice").json()
    assert (got["marks"], got["conversation"]["pause_ms"], got["tuning_error"]) == (["calm", "mute"], 900, "")
    client.post("/sessions/ses_tuned/voice/synthesis", json={"text": "やあ。"})
    assert engine[0][0].endswith("speaker=200&text=%E3%82%84%E3%81%82%E3%80%82")
    assert engine[1][1]["speedScale"] == 0.9


def test_a_change_to_the_tuning_file_counts_from_the_next_request(client, tuned):
    _write(tuned, {"conversation": {"pause_ms": 800}})
    assert client.get("/sessions/ses_tuned/voice").json()["conversation"]["pause_ms"] == 800
    _write(tuned, {"conversation": {"pause_ms": 600}})
    assert client.get("/sessions/ses_tuned/voice").json()["conversation"]["pause_ms"] == 600


@pytest.mark.parametrize("content, reason", [
    (None, "ありません"),
    ("{ not json", "JSON として読めません"),
    ([1, 2], "object で書きます"),
    ({"engine": "http://elsewhere:1"}, "書けない項目があります: engine"),
    ({"speaker": "200"}, "値の形が違います"),
])
def test_a_tuning_file_that_cannot_be_used_leaves_the_setting_and_says_why(client, tuned, engine, content, reason):
    if content is not None:
        _write(tuned, content)
    got = client.get("/sessions/ses_tuned/voice").json()
    assert got["enabled"] and got["marks"] == ["calm", "happy", "sleepy", "mute"]
    assert reason in got["tuning_error"]
    client.post("/sessions/ses_tuned/voice/synthesis", json={"text": "やあ。"})
    assert engine[0][0].startswith("http://127.0.0.1:10101/audio_query?speaker=100&")


def test_why_a_tuning_file_cannot_be_used_is_logged_once(client, tuned, caplog):
    _write(tuned, "{ not json")
    with caplog.at_level("WARNING", logger=voice.logger.name):
        client.get("/sessions/ses_tuned/voice")
        client.get("/sessions/ses_tuned/voice")
    assert sum("voice.json" in r.getMessage() for r in caplog.records) == 1
