"""電話の会話 (= routes/voice_call.py と voice_call/) の試験。

決まり (= voice_call/rules.py) と口の断り方は、 どの環境でも走る。 Pipecat を通す試験は、 電話の会話の部品
(= backend/requirements-voice-call.txt) が入っていなければ飛ばす。
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from backend.routes import voice_call
from backend.tests.test_voice import tabs  # noqa: F401 (= 声のタブの用意を使い回す)
from backend.voice_call.rules import is_unfinished, mark_voice_input, marked, speech_of, split_mark

SETTINGS = {
    "marks": {"calm": {}, "happy": {}},
    "default": "calm",
    "conversation": {"pause_ms": 200, "wait_ms": 300, "unfinished_endings": ["、", "なんか"], "interrupt": True},
}


def _reply(uuid: str, text: str, ts: int, **extra) -> dict:
    return {"type": "assistant", "uuid": uuid, "ts": ts, "message": {"content": [{"type": "text", "text": text}]},
            **extra}


# --- 決まり ---------------------------------------------------------------------------------------------------

def test_the_voice_input_mark_matches_the_screen():
    assert mark_voice_input("明日の天気を教えて") == "[voice] 明日の天気を教えて"
    assert mark_voice_input("[voice] もう付いている") == "[voice] もう付いている"
    for left_alone in ("/clear", "!ls", "#memo", "", "  "):
        assert mark_voice_input(left_alone) == left_alone


def test_an_unfinished_turn_ends_with_a_listed_ending_before_the_punctuation():
    endings = ["、", "なんか", "えーと"]
    assert is_unfinished("それで、", endings)
    assert is_unfinished("それでなんか。", endings)
    assert is_unfinished("えーと ", endings)
    assert not is_unfinished("明日は晴れ。", endings)
    assert not is_unfinished("", endings)


def test_only_the_reply_text_of_the_main_agent_is_spoken():
    assert speech_of(_reply("u1", "今日は晴れです。", 1)) == ("u1:text", "今日は晴れです。")
    assert speech_of(_reply("u2", "下調べ中", 1, parent_tool_use_id="toolu_1")) is None
    tool_only = {"type": "assistant", "uuid": "u3", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}}
    assert speech_of(tool_only) is None
    assert speech_of({"type": "user_message", "uuid": "u4", "text": "こんにちは"}) is None
    assert speech_of(_reply("", "名前の無い物", 1)) is None


def test_a_mark_survives_the_trip_to_the_voice():
    marks = {"calm": {}, "happy": {}}
    assert split_mark(marked("happy", "やった。"), marks) == ("happy", {}, "やった。")
    assert split_mark(marked("", "印なし。"), marks) == (None, {}, "印なし。")
    assert split_mark("[note]一覧に無い印。", marks) == (None, {}, "[note]一覧に無い印。")
    # 印に添えた値も、 合成の部品まで運ぶ
    values = {"intonationScale": 1.2, "speedScale": 0.9}
    assert split_mark(marked("happy", "やった。", values), marks) == ("happy", values, "やった。")


# --- 口 -------------------------------------------------------------------------------------------------------

@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(voice_call.router)
    voice_call._workers.clear()
    return TestClient(app)


OFFER = {"sdp": "v=0", "type": "offer"}


def test_a_tab_that_cannot_hold_a_conversation_is_refused_before_connecting(client, tabs):  # noqa: F811
    for sid, code in (("ses_voice", "voice_listen_not_enabled"), ("ses_plain", "voice_not_enabled")):
        r = client.post(f"/sessions/{sid}/voice/call", json=OFFER)
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == code
    assert client.post("/sessions/ses_missing/voice/call", json=OFFER).status_code == 404


def test_without_the_call_parts_the_backend_says_so(client, tabs, monkeypatch):  # noqa: F811
    monkeypatch.setattr(voice_call.importlib.util, "find_spec", lambda name: None)
    r = client.post("/sessions/ses_listen/voice/call", json=OFFER)
    assert r.status_code == 501
    assert r.json()["detail"]["code"] == "voice_call_unavailable"


def test_a_candidate_before_any_call_is_unknown(client, tabs):  # noqa: F811
    r = client.patch("/sessions/ses_listen/voice/call", json={"pc_id": "pc", "candidates": []})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "voice_call_unknown"


# --- agent の段 (= Pipecat を通す) -----------------------------------------------------------------------------

def _bridge(sent: list[str], events: list[dict] | None = None):
    from backend.voice_call.agent import AgentBridge

    async def send(text: str) -> bool:
        sent.append(text)
        return True

    async def stream():
        await asyncio.sleep(0.05)   # 会話を始めた後に届く
        for event in events or []:
            yield event
        await asyncio.sleep(3600)

    async def utterances(text: str) -> list[dict]:
        return [{"mark": "calm" if not line.startswith("[happy]") else "happy",
                 "text": line.removeprefix("[happy]")} for line in text.split("\n")]

    return AgentBridge(SETTINGS["conversation"], send=send, events=stream, utterances=utterances)


def _said(text: str):
    from pipecat.frames.frames import LLMContextFrame
    from pipecat.processors.aggregators.llm_context import LLMContext

    context = LLMContext()
    context.add_message({"role": "user", "content": text})
    return LLMContextFrame(context=context)


def test_a_finished_turn_goes_to_the_tab():
    pytest.importorskip("pipecat")
    from pipecat.tests.utils import run_test

    sent: list[str] = []
    from pipecat.frames.frames import InterruptionFrame

    asyncio.run(run_test(_bridge(sent), frames_to_send=[_said("明日の天気を教えて")],
                         expected_down_frames=[InterruptionFrame]))
    assert sent == ["明日の天気を教えて"]


def test_an_unfinished_turn_waits_for_the_rest_and_goes_as_one():
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import UserStartedSpeakingFrame
    from pipecat.tests.utils import SleepFrame, run_test

    sent: list[str] = []
    frames = [_said("それで、"), SleepFrame(sleep=0.05), UserStartedSpeakingFrame(), _said("明日は晴れ。")]
    asyncio.run(run_test(_bridge(sent), frames_to_send=frames))
    assert sent == ["それで、明日は晴れ。"]


def test_an_unfinished_turn_goes_alone_once_the_wait_is_over():
    pytest.importorskip("pipecat")
    from pipecat.tests.utils import SleepFrame, run_test

    sent: list[str] = []
    asyncio.run(run_test(_bridge(sent), frames_to_send=[_said("えーとなんか"), SleepFrame(sleep=0.3)]))
    assert sent == ["えーとなんか"]


def test_new_replies_are_spoken_once_with_their_marks():
    pytest.importorskip("pipecat")
    import time

    from pipecat.frames.frames import TTSSpeakFrame
    from pipecat.tests.utils import SleepFrame, run_test

    later = int(time.time() * 1000) + 60_000
    events = [
        _reply("old", "前から在った物。", 0),
        _reply("r1", "晴れです。\n[happy]やった。", later),
        _reply("r1", "晴れです。\n[happy]やった。", later),
        _reply("sub", "下調べ。", later, parent_tool_use_id="t"),
    ]
    down, _ = asyncio.run(run_test(_bridge([], events), frames_to_send=[SleepFrame(sleep=0.2)]))
    assert [f.text for f in down if isinstance(f, TTSSpeakFrame)] == ["[calm]晴れです。", "[happy]やった。"]


def test_the_output_gaps_count_only_short_silences_inside_speech():
    pytest.importorskip("pipecat")
    from backend.voice_call.pipeline import OutputGaps

    gaps = OutputGaps()
    # 話す前の無音 → 話す → 1 枠の途切れ → 話す → 文の間の長い無音 → 話す
    for empty in [True] * 3 + [False] * 4 + [True] + [False] * 2 + [True] * 50 + [False]:
        gaps.saw(empty, late_ms=0.0)
    gaps.saw(False, late_ms=37.0)
    assert (gaps.frames, gaps.gaps, round(gaps.late_max_ms)) == (62, 1, 37)


def test_the_call_log_rotates_and_keeps_only_pipecat_warnings(tmp_path, monkeypatch):
    pytest.importorskip("pipecat")
    import logging

    from loguru import logger as pipecat_logger

    from backend.voice_call import worker

    monkeypatch.setattr(worker, "LOG_PATH", tmp_path / "voice-call.log")
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        worker.setup_logging()
        pipecat_logger.debug("a debug line from pipecat")
        pipecat_logger.warning("a warning from pipecat")
        logging.getLogger("backend.voice_call.pipeline").info("voice call: started")
        for handler in root.handlers:
            handler.flush()
        text = (tmp_path / "voice-call.log").read_text()
    finally:
        for handler in root.handlers[len(before):]:
            root.removeHandler(handler)
            handler.close()
    assert "a warning from pipecat" in text and "voice call: started" in text
    assert "a debug line from pipecat" not in text
    added = [h for h in logging.getLogger().handlers if h not in before]
    assert added == []


def test_after_a_new_turn_is_sent_the_old_reply_is_not_said_until_the_tab_takes_the_turn():
    pytest.importorskip("pipecat")
    import time

    from pipecat.frames.frames import InterruptionFrame, TTSSpeakFrame
    from pipecat.tests.utils import SleepFrame, run_test

    later = int(time.time() * 1000) + 60_000
    events = [
        _reply("old-rest", "前の返事の続き。", later),        # 送った後、 新しい turn の前に届いた
        {"type": "user_message", "uuid": "u-new", "text": "[voice] 次の話", "ts": later},
        _reply("new", "新しい返事。", later + 1),
    ]

    async def scenario():
        sent: list[str] = []
        bridge = _bridge(sent, events)
        down, _ = await run_test(bridge, frames_to_send=[_said("次の話"), SleepFrame(sleep=0.2)])
        return sent, down

    sent, down = asyncio.run(scenario())
    assert sent == ["次の話"]
    assert any(isinstance(f, InterruptionFrame) for f in down)
    assert [f.text for f in down if isinstance(f, TTSSpeakFrame)] == ["[calm]新しい返事。"]


def test_the_volume_of_a_call_is_checked_and_reaches_no_call_when_there_is_none(client, tabs):  # noqa: F811
    assert client.post("/sessions/ses_listen/voice/call/volume", json={"volume": 0.5}).json() == {"calls": 0}
    for bad in (-0.1, 2.1, "loud", None):
        r = client.post("/sessions/ses_listen/voice/call/volume", json={"volume": bad})
        assert r.status_code == 400 and r.json()["detail"]["code"] == "voice_bad_request"
    r = client.post("/sessions/ses_listen/voice/call?volume=3", json=OFFER)
    assert r.status_code == 400


def test_the_volume_scales_the_voice_and_stops_at_the_limit():
    pytest.importorskip("pipecat")
    import numpy as np

    from backend.voice_call.services import scaled

    pcm = np.array([1000, -1000, 30000, -30000], dtype=np.int16).tobytes()
    assert np.frombuffer(scaled(pcm, 0.5), dtype=np.int16).tolist() == [500, -500, 15000, -15000]
    assert np.frombuffer(scaled(pcm, 2.0), dtype=np.int16).tolist() == [2000, -2000, 32767, -32768]
    assert scaled(pcm, 1.0) == pcm
