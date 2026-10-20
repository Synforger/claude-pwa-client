"""電話の会話 (= routes/voice_call.py と voice_call/) の試験。

決まり (= voice_call/rules.py) と口の断り方は、 どの環境でも走る。 Pipecat を通す試験は、 電話の会話の部品
(= backend/requirements-voice-call.txt) が入っていなければ飛ばす。
"""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from backend.core.speech import mark_voice_input
from backend.routes import voice_call
from backend.tests.test_voice import tabs  # noqa: F401 (= 声のタブの用意を使い回す)
from backend.voice_call.rules import (
    is_own_voice,
    is_unfinished,
    marked,
    shown_reply_text,
    shown_user_text,
    speech_of,
    split_mark,
)

SETTINGS = {
    "marks": {"calm": {}, "happy": {}},
    "default": "calm",
    "conversation": {"pause_ms": 200, "wait_ms": 300, "resume_ms": 50, "unfinished_endings": ["、", "なんか"],
                     "interrupt": True},
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


class _FakeCall:
    """会話の process の偽物: 申し込みに answer を返し、 finish が立つまで走り続ける (= 閉じる時に handover を出す)。"""

    def __init__(self, finish, *, pc_id: str = "pc1", handover: dict | None = None, starts: list | None = None,
                 received: list | None = None, answer_after=None):
        import json

        self._finish = finish
        self.returncode = None
        answer = {"type": "answer", "answer": {"sdp": "v=0", "type": "answer", "pc_id": pc_id}}

        class _In:
            def write(self, data):
                message = json.loads(data)
                if starts is not None and message.get("type") == "start":
                    starts.append(message)
                if received is not None:
                    received.append((pc_id, message["type"]))

            async def drain(self):
                pass

        class _Out:
            def __init__(self):
                self._lines = [answer]

            async def readline(self):
                if self._lines:
                    while answer_after is not None and not answer_after.is_set():
                        await asyncio.sleep(0.01)
                    return (json.dumps(self._lines.pop(0)) + "\n").encode()
                while not finish.is_set():
                    await asyncio.sleep(0.01)
                if handover is not None and not getattr(self, "_handed", False):
                    self._handed = True
                    return (json.dumps({"type": "handover", **handover}) + "\n").encode()
                return b""

        self.stdin, self.stdout = _In(), _Out()

    async def wait(self):
        while not self._finish.is_set():
            await asyncio.sleep(0.01)
        self.returncode = 0
        return 0

    def kill(self):
        self.killed = True
        self._finish.set()


def test_a_tab_is_on_a_call_from_the_answer_until_the_call_process_ends(tabs, monkeypatch):  # noqa: F811
    import threading
    import time

    from backend.state import is_session_on_call

    finish = threading.Event()

    async def spawn(*args, **kwargs):
        return _FakeCall(finish)

    monkeypatch.setattr(voice_call.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(voice_call.asyncio, "create_subprocess_exec", spawn)
    app = FastAPI()
    app.include_router(voice_call.router)
    voice_call._workers.clear()
    with TestClient(app) as c:   # 通話の終わりを待つ task が、 申し込みの後も走り続けるように
        assert c.post("/sessions/ses_listen/voice/call", json=OFFER).status_code == 200
        assert is_session_on_call("ses_listen")
        assert not is_session_on_call("ses_voice")
        finish.set()
        deadline = time.monotonic() + 2
        while is_session_on_call("ses_listen") and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not is_session_on_call("ses_listen")


def test_a_redial_gets_what_the_closed_call_had_left_to_say_and_a_new_call_does_not(tabs, monkeypatch):  # noqa: F811
    import threading

    left = {"since_ms": 5, "sentences": [{"mark": "calm", "text": "続きの文。"}]}
    finishes = [threading.Event() for _ in range(3)]
    starts: list[dict] = []
    calls = iter([dict(pc_id="pc1", handover=left), dict(pc_id="pc2", handover=left), dict(pc_id="pc3")])

    async def spawn(*args, **kwargs):
        return _FakeCall(finishes[len(starts)], starts=starts, **next(calls))

    monkeypatch.setattr(voice_call.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(voice_call.asyncio, "create_subprocess_exec", spawn)
    app = FastAPI()
    app.include_router(voice_call.router)
    voice_call._workers.clear()
    voice_call._handovers.clear()
    with TestClient(app) as c:
        assert c.post("/sessions/ses_listen/voice/call", json=OFFER).status_code == 200
        # つなぎ直し: 前の通話が閉じ終えるのを待ち、 その鳴り残しを受け取る
        threading.Timer(0.1, finishes[0].set).start()
        assert c.post("/sessions/ses_listen/voice/call?resume=1", json=OFFER).status_code == 200
        # つなぎ直しでない通話は、 前の鳴り残しを受け取らない
        finishes[1].set()
        threading.Timer(0.1, lambda: None).start()
        import time
        time.sleep(0.2)
        assert c.post("/sessions/ses_listen/voice/call", json=OFFER).status_code == 200
        finishes[2].set()
    assert starts[0]["resume"] is None
    assert starts[1]["resume"] == left
    assert starts[2]["resume"] is None


def _call_app(monkeypatch, spawn) -> TestClient:
    monkeypatch.setattr(voice_call.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(voice_call.asyncio, "create_subprocess_exec", spawn)
    app = FastAPI()
    app.include_router(voice_call.router)
    voice_call._workers.clear()
    voice_call._handovers.clear()
    voice_call._latest.clear()
    return TestClient(app)


def test_a_new_call_tells_the_older_call_of_the_same_tab_to_end(tabs, monkeypatch):  # noqa: F811
    import threading

    finishes = [threading.Event() for _ in range(2)]
    received: list[tuple[str, str]] = []
    spawned: list[str] = []

    async def spawn(*args, **kwargs):
        spawned.append(f"pc{len(spawned) + 1}")
        return _FakeCall(finishes[len(spawned) - 1], pc_id=spawned[-1], received=received)

    with _call_app(monkeypatch, spawn) as c:
        assert c.post("/sessions/ses_listen/voice/call", json=OFFER).status_code == 200
        assert c.post("/sessions/ses_listen/voice/call", json=OFFER).status_code == 200
        for finish in finishes:
            finish.set()
    # 1 本目は 2 本目の申し込みで「終われ」 を受けた。 2 本目は受けていない
    assert ("pc1", "end") in received
    assert ("pc2", "end") not in received


def test_a_redial_overtaken_while_it_waits_is_not_started(tabs, monkeypatch):  # noqa: F811
    import threading
    import time

    finishes = [threading.Event() for _ in range(3)]
    spawned: list[str] = []

    async def spawn(*args, **kwargs):
        spawned.append(f"pc{len(spawned) + 1}")
        return _FakeCall(finishes[len(spawned) - 1], pc_id=spawned[-1])

    results: dict[str, object] = {}
    with _call_app(monkeypatch, spawn) as c:
        # 1 本目は「終われ」 を受けても閉じない (= つながらないまま待っている通話)
        assert c.post("/sessions/ses_listen/voice/call", json=OFFER).status_code == 200
        # つなぎ直しは 1 本目が閉じるのを待つ。 その間に、 後から別の申し込みが来る
        waiting = threading.Thread(
            target=lambda: results.update(redial=c.post("/sessions/ses_listen/voice/call?resume=1", json=OFFER)))
        waiting.start()
        time.sleep(0.2)
        assert c.post("/sessions/ses_listen/voice/call", json=OFFER).status_code == 200
        finishes[0].set()
        waiting.join(5)
        for finish in finishes:
            finish.set()
    redial = results["redial"]
    assert redial.status_code == 409
    assert redial.json()["detail"]["code"] == "voice_call_superseded"
    # 待っていたつなぎ直しは通話を立てなかった (= 立ったのは 1 本目と、 後から来た 1 本だけ)
    assert spawned == ["pc1", "pc2"]


def test_a_call_overtaken_before_its_answer_is_closed_and_refused(tabs, monkeypatch):  # noqa: F811
    import threading
    import time

    finishes = [threading.Event() for _ in range(2)]
    answer_first = threading.Event()
    calls: list[_FakeCall] = []

    async def spawn(*args, **kwargs):
        index = len(calls)
        calls.append(_FakeCall(finishes[index], pc_id=f"pc{index + 1}",
                               answer_after=answer_first if index == 0 else None))
        return calls[-1]

    results: dict[str, object] = {}
    with _call_app(monkeypatch, spawn) as c:
        slow = threading.Thread(
            target=lambda: results.update(first=c.post("/sessions/ses_listen/voice/call", json=OFFER)))
        slow.start()
        time.sleep(0.2)
        assert c.post("/sessions/ses_listen/voice/call", json=OFFER).status_code == 200
        answer_first.set()
        slow.join(5)
        # 遅れて answer を返した 1 本目は閉じられ、 タブの通話には残らない (= 後から来た 2 本目だけ)
        assert getattr(calls[0], "killed", False)
        assert list(voice_call._workers) == ["pc2"]
        for finish in finishes:
            finish.set()
    first = results["first"]
    assert first.status_code == 409
    assert first.json()["detail"]["code"] == "voice_call_superseded"


def test_without_the_call_parts_the_backend_says_so(client, tabs, monkeypatch):  # noqa: F811
    monkeypatch.setattr(voice_call.importlib.util, "find_spec", lambda name: None)
    r = client.post("/sessions/ses_listen/voice/call", json=OFFER)
    assert r.status_code == 501
    assert r.json()["detail"]["code"] == "voice_call_unavailable"


def test_a_candidate_before_any_call_is_unknown(client, tabs):  # noqa: F811
    r = client.patch("/sessions/ses_listen/voice/call", json={"pc_id": "pc", "candidates": []})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "voice_call_unknown"


def test_the_picture_shows_what_was_said_without_marks_and_no_envelopes():
    assert shown_user_text("[voice] 明日の天気を教えて") == "明日の天気を教えて"
    assert shown_user_text("画面から打った文") == "画面から打った文"
    for hidden in (None, "", "  ", "Message from another session, relayed by the client: …",
                   "Automatic session rollover, sent by the client …", "<session-rollover phase=\"start\">"):
        assert shown_user_text(hidden) is None
    assert shown_reply_text("[calm]晴れです。\n[mute]表は画面で。\n[happy i=1.2]やった。") == "晴れです。\n表は画面で。\nやった。"
    assert shown_reply_text("[1] は脚注のまま") == "[1] は脚注のまま"
    for interrupt in ("[Request interrupted by user]", "[Request interrupted by user for tool use]"):
        assert shown_user_text(interrupt) is None


def test_the_picture_shows_an_image_as_its_description_outside_code():
    reply = "[calm]図を置いた。\n![売上の推移](/srv/shared/chart.png) と ![](https://example.com/a.png)\n```\n![そのまま](x.png)\n```"
    assert shown_reply_text(reply) == "図を置いた。\n🖼 売上の推移 と 🖼 画像\n```\n![そのまま](x.png)\n```"


def test_the_picture_gets_the_reply_as_markdown_without_the_marks():
    # 小窓 (= app の ChatMarkdown.swift) が表・見出し・箇条書き・コードの枠まで描くので、 markdown は崩さずに送る
    reply = "\n".join([
        "[calm]## 結果", "",
        "| 名前 | 値 |", "|------|---:|", "| A | **1** |", "",
        "- 1 つ目", "  - 入れ子", "```", "src/", "└── a.py", "```",
        "[link](https://example.com) は残す",
    ])
    assert shown_reply_text(reply) == reply.removeprefix("[calm]")


# --- agent の段 (= Pipecat を通す) -----------------------------------------------------------------------------

def _bridge(sent: list[str], events: list[dict] | None = None, stops: list[str] | None = None, **kwargs):
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

    async def interrupt() -> bool:
        stops.append("stop")
        return True

    return AgentBridge(SETTINGS["conversation"], send=send, events=stream, utterances=utterances,
                       interrupt=interrupt if stops is not None else None, **kwargs)


def _said(text: str):
    from pipecat.frames.frames import LLMContextFrame
    from pipecat.processors.aggregators.llm_context import LLMContext

    context = LLMContext()
    context.add_message({"role": "user", "content": text})
    return LLMContextFrame(context=context)


def test_a_finished_turn_goes_to_the_tab():
    pytest.importorskip("pipecat")
    from pipecat.tests.utils import SleepFrame, run_test

    sent: list[str] = []
    from pipecat.frames.frames import InterruptionFrame
    from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame

    # 下流へは、 前の turn の声を止める割り込みと、 小窓への「考えています」 だけ
    asyncio.run(run_test(_bridge(sent), frames_to_send=[_said("明日の天気を教えて"), SleepFrame(sleep=0.2)],
                         expected_down_frames=[InterruptionFrame, RTVIServerMessageFrame]))
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


def test_a_reply_to_a_newer_turn_drops_what_is_left_of_the_older_one():
    # 返事の途中に、 別のタブからの連絡で新しい turn が始まり、 その返事が届いた: 古い方の残りを言い続けていた
    pytest.importorskip("pipecat")
    import time

    from pipecat.frames.frames import InterruptionFrame, TTSSpeakFrame
    from pipecat.tests.utils import SleepFrame, run_test

    later = int(time.time() * 1000) + 60_000
    events = [
        _reply("r1", "前の返事の 1 文目。\n前の返事の 2 文目。", later),
        {"type": "user_message", "uuid": "m1", "text": "Message from another session …", "ts": later + 1},
        _reply("r2", "新しい返事。", later + 2),
    ]
    down, _ = asyncio.run(run_test(_bridge([], events), frames_to_send=[SleepFrame(sleep=0.2)]))
    said = [type(f).__name__ if isinstance(f, InterruptionFrame) else f.text
            for f in down if isinstance(f, (TTSSpeakFrame, InterruptionFrame))]
    assert said == ["[calm]前の返事の 1 文目。", "[calm]前の返事の 2 文目。", "InterruptionFrame", "[calm]新しい返事。"]


def test_a_newer_reply_of_the_same_turn_also_drops_what_is_left_of_the_older_one():
    # ツールの合間に書いた文も、 新しい返事 (= いつも一番新しい返事を聞く。 2026-10-19 に同じ turn の中で切り替わらなかった)
    pytest.importorskip("pipecat")
    import time

    from pipecat.frames.frames import InterruptionFrame, TTSSpeakFrame
    from pipecat.tests.utils import SleepFrame, run_test

    later = int(time.time() * 1000) + 60_000
    events = [_reply("r1", "調べるね。\nまず表を見る。", later), _reply("r2", "分かった。", later + 1)]
    down, _ = asyncio.run(run_test(_bridge([], events), frames_to_send=[SleepFrame(sleep=0.2)]))
    said = [type(f).__name__ if isinstance(f, InterruptionFrame) else f.text
            for f in down if isinstance(f, (TTSSpeakFrame, InterruptionFrame))]
    assert said == ["[calm]調べるね。", "[calm]まず表を見る。", "InterruptionFrame", "[calm]分かった。"]


def test_a_reply_after_the_older_one_was_said_cuts_nothing():
    pytest.importorskip("pipecat")
    import time

    from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame, InterruptionFrame
    from pipecat.tests.utils import SleepFrame, run_test

    later = int(time.time() * 1000) + 60_000

    async def stream():
        await asyncio.sleep(0.05)
        yield _reply("r1", "調べるね。", later)
        await asyncio.sleep(0.2)   # 1 つ目を鳴らし終えた後に届く
        yield _reply("r2", "分かった。", later + 1)
        await asyncio.sleep(3600)

    from backend.voice_call.agent import AgentBridge

    async def send(text: str) -> bool:
        return True

    async def utterances(text: str) -> list[dict]:
        return [{"mark": "calm", "text": text}]

    bridge = AgentBridge(SETTINGS["conversation"], send=send, events=stream, utterances=utterances)
    frames = [SleepFrame(sleep=0.1), BotStartedSpeakingFrame(), BotStoppedSpeakingFrame(), SleepFrame(sleep=0.3)]
    down, _ = asyncio.run(run_test(bridge, frames_to_send=frames))
    assert not any(isinstance(f, InterruptionFrame) for f in down)


def test_the_volume_of_a_call_is_checked_and_reaches_no_call_when_there_is_none(client, tabs):  # noqa: F811
    assert client.post("/sessions/ses_listen/voice/call/volume", json={"volume": 0.5}).json() == {"calls": 0}
    for bad in (-0.1, 2.1, "loud", None):
        r = client.post("/sessions/ses_listen/voice/call/volume", json={"volume": bad})
        assert r.status_code == 400 and r.json()["detail"]["code"] == "voice_bad_request"
    r = client.post("/sessions/ses_listen/voice/call?volume=3", json=OFFER)
    assert r.status_code == 400


def test_the_call_gain_from_the_config_scales_the_screen_volume_and_defaults_to_none():
    from backend import config
    from backend.routes.voice_call import _with_call_gain

    def written(extra: dict) -> None:
        config.CONFIG_PATH.write_text(json.dumps({**json.loads(config.CONFIG_PATH.read_text()), **extra}))
        config.get_config.cache_clear()

    assert _with_call_gain(0.5) == 0.5
    written({"voice_call_gain_db": -20})
    assert _with_call_gain(1.0) == pytest.approx(0.1)
    assert _with_call_gain(0.5) == pytest.approx(0.05)
    for unset in ({"voice_call_gain_db": "quiet"}, {"voice_call_gain_db": True}):
        written(unset)
        assert _with_call_gain(0.5) == 0.5


def test_the_volume_scales_the_voice_and_stops_at_the_limit():
    pytest.importorskip("pipecat")
    import numpy as np

    from backend.voice_call.services import scaled

    pcm = np.array([1000, -1000, 30000, -30000], dtype=np.int16).tobytes()
    assert np.frombuffer(scaled(pcm, 0.5), dtype=np.int16).tolist() == [500, -500, 15000, -15000]
    assert np.frombuffer(scaled(pcm, 2.0), dtype=np.int16).tolist() == [2000, -2000, 32767, -32768]
    assert scaled(pcm, 1.0) == pcm


def test_the_volume_moved_while_a_reply_is_said_reaches_the_rest_of_it(monkeypatch):
    # 返事の文は話し終えるより先に全部作られる。 作る時に倍率を掛けていた間は、 話している途中に動かしたつまみが
    # その返事に効かなかった (= 2026-10-15、 8 文の返事が 11 秒で作り終わり、 その後の 30 秒の間に動かした)
    pytest.importorskip("pipecat")
    import numpy as np
    from pipecat.transports.smallwebrtc.transport import RawAudioTrack

    from backend.voice_call.pipeline import scale_output
    from backend.voice_call.services import Volume

    monkeypatch.setattr(RawAudioTrack, "add_audio_bytes", RawAudioTrack.add_audio_bytes)   # 試験の後に戻す
    volume = Volume(1.0)
    scale_output(volume)
    track = RawAudioTrack(sample_rate=24000)
    reply = np.full(240 * 2, 1000, dtype=np.int16).tobytes()   # 作り終わった返事の、 20 ms 分
    sent_first, rest = reply[:480], reply[480:]

    async def send():
        track.add_audio_bytes(sent_first)
        volume.value = 0.5   # 前半を送った所でつまみを動かす
        track.add_audio_bytes(rest)

    asyncio.run(send())
    levels = [int(np.frombuffer(chunk, dtype=np.int16)[0]) for chunk, _ in track._chunk_queue]
    assert levels == [1000, 500]


# --- 長い発話 (= 途中の間で「言い終えた」 と判定される) --------------------------------------------------------

def _talk(conversation: dict, gap: float, send_secs: float) -> list[str]:
    """本物の発話のまとめ役と agent の段をつなぎ、 3 つの区間を gap 秒ずつ空けて話す。 判定は毎回「言い終えた」。"""
    from pipecat.audio.turn.base_turn_analyzer import BaseTurnAnalyzer, BaseTurnParams, EndOfTurnState
    from pipecat.frames.frames import TranscriptionFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMContextAggregatorPair,
        LLMUserAggregatorParams,
    )
    from pipecat.tests.utils import SleepFrame, run_test
    from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import TurnAnalyzerUserTurnStopStrategy
    from pipecat.turns.user_turn_strategies import UserTurnStrategies

    from backend.voice_call.agent import AgentBridge

    class AlwaysComplete(BaseTurnAnalyzer):
        @property
        def speech_triggered(self):
            return False

        @property
        def params(self):
            return BaseTurnParams()

        def append_audio(self, buffer, is_speech):
            return EndOfTurnState.INCOMPLETE

        async def analyze_end_of_turn(self):
            return EndOfTurnState.COMPLETE, None

        def clear(self):
            pass

    sent: list[str] = []

    async def send(text: str) -> bool:
        await asyncio.sleep(send_secs)   # 送るのに掛かる時間 (= 本物は数秒掛かることがある)
        sent.append(text)
        return True

    async def stream():
        await asyncio.sleep(3600)
        yield {}

    async def utterances(text: str) -> list[dict]:
        return []

    aggregator, _ = LLMContextAggregatorPair(LLMContext(), user_params=LLMUserAggregatorParams(
        user_turn_strategies=UserTurnStrategies(stop=[TurnAnalyzerUserTurnStopStrategy(turn_analyzer=AlwaysComplete())]),
        user_mute_strategies=[]))
    bridge = AgentBridge(conversation, send=send, events=stream, utterances=utterances)
    frames = []
    for i, text in enumerate(("一つ目の区間", "二つ目の区間", "三つ目の区間")):
        frames += [VADUserStartedSpeakingFrame(start_secs=0.2), SleepFrame(sleep=0.1),
                   VADUserStoppedSpeakingFrame(stop_secs=0.2), SleepFrame(sleep=0.02),
                   TranscriptionFrame(text, "u", "t"), SleepFrame(sleep=gap if i < 2 else send_secs * 4)]
    asyncio.run(run_test(Pipeline([aggregator, bridge]), frames_to_send=frames))
    return sent


def test_a_part_said_before_a_pause_is_not_lost_when_the_rest_starts_while_it_is_sent():
    # 途中の間で「言い終えた」 と判定された区間を送っている間に続きを話し始めると、 まとめ役の割り込みが送る処理を
    # 打ち切り、 その区間が消えていた (= 長く話すと最後の区間だけが届いた)
    pytest.importorskip("pipecat")
    sent = _talk({**SETTINGS["conversation"], "resume_ms": 0}, gap=0.15, send_secs=0.4)
    assert sent == ["一つ目の区間", "二つ目の区間", "三つ目の区間"]


def test_a_part_said_before_a_pause_is_joined_with_the_rest_that_starts_within_the_wait():
    pytest.importorskip("pipecat")
    sent = _talk({**SETTINGS["conversation"], "resume_ms": 600}, gap=0.15, send_secs=0.1)
    assert sent == ["一つ目の区間二つ目の区間三つ目の区間"]


def test_a_turn_still_waiting_when_the_call_ends_is_sent():
    pytest.importorskip("pipecat")
    from pipecat.tests.utils import run_test

    sent: list[str] = []
    bridge = _bridge(sent)
    bridge._resume_secs = 30   # 待ちの間に通話が終わる
    asyncio.run(run_test(bridge, frames_to_send=[_said("最後の一言")]))
    assert sent == ["最後の一言"]


def test_a_sentence_that_takes_long_to_make_is_still_said():
    # Pipecat は 1 文の音を stop_frame_timeout_s で待つのをやめ、 「音が無いまま終わった」 の error を出す。 作るのに
    # それより掛かる長い文で、 通話が切れていた (= 2026-10-14、 90 文字の文が 3.3 秒)
    pytest.importorskip("pipecat")
    import io
    import wave

    from pipecat.frames.frames import ErrorFrame, TTSAudioRawFrame, TTSSpeakFrame
    from pipecat.tests.utils import SleepFrame, run_test

    from backend.voice_call.services import VoiceTTS

    sound = io.BytesIO()
    with wave.open(sound, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\x00\x01" * 2400)

    class SlowVoice:
        async def synthesize(self, text, mark, values=None):
            await asyncio.sleep(1.0)
            return sound.getvalue()

    tts = VoiceTTS(SlowVoice(), ["calm"], stop_frame_timeout_s=0.3)
    down, up = asyncio.run(run_test(tts, frames_to_send=[TTSSpeakFrame("長い文です。"), SleepFrame(sleep=1.5)]))
    assert any(isinstance(f, TTSAudioRawFrame) for f in down)
    assert not [f for f in [*down, *up] if isinstance(f, ErrorFrame)]   # error は上流へ流れる



# --- 小窓 (= iPhone の app の PiP へ送る会話と状態) ----------------------------------------------------------------

def _shown(down) -> list[dict]:
    from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame

    return [f.data for f in down if isinstance(f, RTVIServerMessageFrame)]


def test_the_picture_gets_the_tab_lines_with_the_recent_ones_from_before_the_call_first():
    pytest.importorskip("pipecat")
    import time

    from pipecat.tests.utils import SleepFrame, run_test

    later = int(time.time() * 1000) + 60_000
    events = [
        {"type": "user_message", "text": "[voice] 前から在った発話", "uuid": "u0", "ts": 0},
        _reply("old", "前から在った返事。", 0),
        {"type": "user_message", "text": "[voice] 明日の天気は", "uuid": "u1", "ts": later},
        {"type": "user_message", "text": "Message from another session, relayed by the client …", "uuid": "u2",
         "ts": later},
        _reply("r1", "[calm]晴れです。\n[mute]表は画面に置きました。", later),
        _reply("r1", "[calm]晴れです。\n[mute]表は画面に置きました。", later),
        _reply("sub", "下調べ。", later, parent_tool_use_id="t"),
    ]
    down, _ = asyncio.run(run_test(_bridge([], events), frames_to_send=[SleepFrame(sleep=0.2)]))
    assert [d for d in _shown(down) if d["pip"] == "line"] == [
        {"pip": "line", "who": "user", "text": "前から在った発話"},      # 会話を始める前の分 (= まとめて先に)
        {"pip": "line", "who": "agent", "text": "前から在った返事。"},
        {"pip": "line", "who": "user", "text": "明日の天気は"},
        {"pip": "line", "who": "agent", "text": "晴れです。\n表は画面に置きました。"},
    ]


def test_the_picture_replaces_a_turn_sent_again_under_the_same_parent():
    # 声の会話は、 途中の間で区切られて先に送った前半を取り消し、 後半をつなげて送り直す。 claude は取り消した発話を
    # 記録に残し、 送り直した発話を同じ親に付ける。 小窓には 1 区間ずつ長くなる発話が並んでいた (= 2026-10-15)
    pytest.importorskip("pipecat")
    import time

    from pipecat.tests.utils import SleepFrame, run_test

    later = int(time.time() * 1000) + 60_000
    events = [
        {"type": "user_message", "text": "[voice] 前から在った前半", "uuid": "o1", "parentUuid": "Q", "ts": 0},
        {"type": "user_message", "text": "[voice] 前から在った前半 後半", "uuid": "o2", "parentUuid": "Q", "ts": 0},
        {"type": "user_message", "text": "[voice] てか、次のやつは。", "uuid": "u1", "parentUuid": "P", "ts": later},
        {"type": "user_message", "text": "[voice] てか、次のやつは。 時間がかかりそう。", "uuid": "u2", "parentUuid": "P",
         "ts": later},
        _reply("r1", "[calm]次は比べる所。", later),
        {"type": "user_message", "text": "[voice] なるほど。", "uuid": "u3", "parentUuid": "R", "ts": later},
    ]
    down, _ = asyncio.run(run_test(_bridge([], events), frames_to_send=[SleepFrame(sleep=0.2)]))
    assert [d for d in _shown(down) if d["pip"] == "line"] == [
        {"pip": "line", "who": "user", "text": "前から在った前半 後半"},   # 溜めている間に置き換えた
        {"pip": "line", "who": "user", "text": "てか、次のやつは。"},
        {"pip": "line", "who": "user", "text": "てか、次のやつは。 時間がかかりそう。", "replace": True},
        {"pip": "line", "who": "agent", "text": "次は比べる所。"},
        {"pip": "line", "who": "user", "text": "なるほど。"},
    ]


def test_the_picture_gets_only_the_last_lines_from_before_the_call_once_the_record_settles():
    pytest.importorskip("pipecat")
    from pipecat.tests.utils import SleepFrame, run_test

    from backend.voice_call.agent import HISTORY_SETTLE_SECS, PICTURE_HISTORY

    events = [{"type": "user_message", "text": f"発話 {i}", "uuid": f"u{i}", "ts": i + 1} for i in range(PICTURE_HISTORY + 5)]
    down, _ = asyncio.run(run_test(_bridge([], events), frames_to_send=[SleepFrame(sleep=HISTORY_SETTLE_SECS + 0.2)]))
    lines = [d["text"] for d in _shown(down) if d["pip"] == "line"]
    assert lines == [f"発話 {i}" for i in range(5, PICTURE_HISTORY + 5)]


def test_the_picture_state_follows_speaking_sending_and_the_voice():
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame, UserStartedSpeakingFrame
    from pipecat.tests.utils import SleepFrame, run_test

    frames = [UserStartedSpeakingFrame(), _said("明日の天気を教えて"), SleepFrame(sleep=0.2),
              BotStartedSpeakingFrame(), BotStoppedSpeakingFrame()]
    down, _ = asyncio.run(run_test(_bridge([]), frames_to_send=frames))
    assert [d["state"] for d in _shown(down) if d["pip"] == "state"] == ["listening", "thinking", "speaking", "waiting"]


def _speech(on: bool):
    from pipecat.processors.frameworks.rtvi import RTVIClientMessageFrame

    return RTVIClientMessageFrame(msg_id="m1", type="voice-speech", data={"on": on})


def test_with_the_speech_off_replies_are_shown_but_not_said_and_turning_it_off_stops_the_voice():
    pytest.importorskip("pipecat")
    import time

    from pipecat.frames.frames import InterruptionFrame, TTSSpeakFrame
    from pipecat.processors.frameworks.rtvi import RTVIClientMessageFrame
    from pipecat.tests.utils import SleepFrame, run_test

    later = int(time.time() * 1000) + 60_000

    async def stream_after_switch(bridge):
        down, _ = await run_test(bridge, frames_to_send=[_speech(False), SleepFrame(sleep=0.2)])
        return down

    bridge = _bridge([], [_reply("r1", "晴れです。", later)])
    down = asyncio.run(stream_after_switch(bridge))
    assert not any(isinstance(f, TTSSpeakFrame) for f in down)                 # 声にしない
    assert any(isinstance(f, InterruptionFrame) for f in down)                 # 切った時に鳴っている声を止める
    assert {"pip": "line", "who": "agent", "text": "晴れです。"} in _shown(down)   # 小窓には出す
    assert not any(isinstance(f, RTVIClientMessageFrame) for f in down)


def test_a_call_started_with_the_speech_off_says_nothing_until_it_is_turned_on():
    pytest.importorskip("pipecat")
    import time

    from pipecat.frames.frames import TTSSpeakFrame
    from pipecat.tests.utils import SleepFrame, run_test

    from backend.voice_call.agent import AgentBridge

    later = int(time.time() * 1000) + 60_000
    events = [_reply("r1", "晴れです。", later)]
    quiet = _bridge([], events)
    bridge = AgentBridge(SETTINGS["conversation"], send=quiet._send, events=quiet._events,
                         utterances=quiet._utterances, speech=False)
    down, _ = asyncio.run(run_test(bridge, frames_to_send=[SleepFrame(sleep=0.2), _speech(True), SleepFrame(sleep=0.05)]))
    assert not any(isinstance(f, TTSSpeakFrame) for f in down)   # 前の返事は、 入れ直しても言わない



# --- 自分の声 (= スピーカーの返事がマイクに入って、 人の発話として届いた) ----------------------------------------

def test_what_was_heard_is_its_own_voice_when_it_is_part_of_the_sentence_being_said():
    # 2026-10-15 に実際に届いた 2 件 (= 返事の頭の「3 つの」 が、 聞き取りでは「3つの」 になった)
    assert is_own_voice("3つの", ["そう。整理すると 3 つの立ち位置がある。"])
    assert is_own_voice("3つの", ["3 つの箱の結果を表に出した。"])
    assert is_own_voice("三つの", ["3 つの箱の結果を表に出した。"])
    # 文の境目を跨いで聞こえた分
    assert is_own_voice("出した。 seed", ["3 つの箱の結果を表に出した。", "seed 9 が当たり。"])
    assert not is_own_voice("ちょっと待って", ["3 つの箱の結果を表に出した。"])
    assert not is_own_voice("、", ["あ、うん。"])


def _cut_reply(heard: str, *, finished_first: bool = False, **bridge_kwargs):
    """2 文の返事を鳴らしている途中で止められ、 heard が人の発話として届く。 返すのは (送った物, 声の段へ渡した文)。"""
    import time

    from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame, InterruptionFrame, TTSSpeakFrame
    from pipecat.tests.utils import SleepFrame, run_test

    later = int(time.time() * 1000) + 60_000
    events = [_reply("r1", "3 つの箱の結果を表に出した。\nseed 9 が当たり。", later)]
    frames = [SleepFrame(sleep=0.2), BotStartedSpeakingFrame()]
    if finished_first:
        frames += [BotStoppedSpeakingFrame(), BotStartedSpeakingFrame()]
    frames += [InterruptionFrame(), BotStoppedSpeakingFrame(), _said(heard), SleepFrame(sleep=0.2)]
    sent: list[str] = []
    down, _ = asyncio.run(run_test(_bridge(sent, events, **bridge_kwargs), frames_to_send=frames))
    return sent, [f.text for f in down if isinstance(f, TTSSpeakFrame)]


def test_its_own_voice_is_not_sent_and_the_cut_sentence_is_said_again():
    pytest.importorskip("pipecat")
    sent, said = _cut_reply("3つの")
    assert sent == []
    assert said == ["[calm]3 つの箱の結果を表に出した。", "[calm]seed 9 が当たり。",
                    "[calm]3 つの箱の結果を表に出した。", "[calm]seed 9 が当たり。"]


def test_a_real_interruption_is_sent_and_the_reply_is_not_said_again():
    pytest.importorskip("pipecat")
    sent, said = _cut_reply("ちょっと待って")
    assert sent == ["ちょっと待って"]
    assert said == ["[calm]3 つの箱の結果を表に出した。", "[calm]seed 9 が当たり。"]


def test_a_reply_cut_in_its_second_sentence_is_said_again_from_the_second():
    pytest.importorskip("pipecat")
    # 1 文目の終わりが聞こえた (= 鳴り終えた 1 文目も比べる)
    sent, said = _cut_reply("表に出した", finished_first=True)
    assert sent == []
    assert said == ["[calm]3 つの箱の結果を表に出した。", "[calm]seed 9 が当たり。", "[calm]seed 9 が当たり。"]


# 書いた文字と声がずれる文の読み (= engine の拍のカナ)
READINGS = {"3 つの箱の結果を表に出した。": "ミッツノハコノケッカヲヒョウニダシタ", "seed 9 が当たり。": "シードキュウガアタリ",
            "±10 は押しても壊れない。": "プラスジュウワオシテモコワレナイ", "シード": "シード", "プラス": "プラス",
            "ちょっと待って": "チョットマッテ"}


async def _reading(text: str) -> str:
    return READINGS.get(text, "")


def test_its_own_voice_written_differently_from_how_it_sounds_is_seen_by_its_reading():
    pytest.importorskip("pipecat")
    sent, said = _cut_reply("シード", finished_first=True, reading=_reading)
    assert sent == []
    assert said == ["[calm]3 つの箱の結果を表に出した。", "[calm]seed 9 が当たり。", "[calm]seed 9 が当たり。"]
    # 読みが無ければ、 書いた文字だけで見分ける (= 人の発話として送る)
    sent, _ = _cut_reply("シード", finished_first=True)
    assert sent == ["シード"]


def test_the_client_reads_a_record_line_longer_than_the_reader_limit():
    # 画像を読んだ結果のような 1 MB を超える行で、 aiohttp の行読みは止まっていた (= その後の返事が届かなかった)
    pytest.importorskip("aiohttp")
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    from backend.voice_call.client import BackendClient

    big = {"type": "user_message", "text": "x" * 1_500_000}

    async def stream_with_data(request):
        response = web.StreamResponse()
        await response.prepare(request)
        body = "data: " + json.dumps({"ch": "jsonl", "ev": big}) + "\n\n"
        for start in range(0, len(body), 7000):
            await response.write(body[start:start + 7000].encode())
        await response.write(b'data: {"ch": "jsonl", "ev": {"type": "user_message", "text": "after"}}\n\n')
        return response

    app = web.Application()
    app.router.add_get("/stream/unified", stream_with_data)

    async def scenario():
        async with TestServer(app) as server, BackendClient(str(server.make_url("")), "ses_a", "phone-1") as backend:
            return [event async for event in backend.events()]

    got = asyncio.run(scenario())
    assert [len(e["text"]) for e in got] == [1_500_000, 5]


def test_a_broken_reply_stream_is_reconnected_and_nothing_is_said_twice(monkeypatch, caplog):
    pytest.importorskip("pipecat")
    import time

    from pipecat.frames.frames import TTSSpeakFrame
    from pipecat.tests.utils import SleepFrame, run_test

    import backend.voice_call.agent as agent
    from backend.voice_call.agent import AgentBridge
    monkeypatch.setattr(agent, "REPLIES_RETRY_SECS", 0.05)

    later = int(time.time() * 1000) + 60_000
    rounds = [0]

    async def stream():
        rounds[0] += 1
        await asyncio.sleep(0.02)
        yield _reply("r1", "最初の返事。", later)
        if rounds[0] == 1:
            raise ValueError("the line was too long")
        yield _reply("r2", "つなぎ直した後の返事。", later + 1)
        await asyncio.sleep(3600)

    async def send(text: str) -> bool:
        return True

    async def utterances(text: str) -> list[dict]:
        return [{"mark": "calm", "text": text}]

    bridge = AgentBridge(SETTINGS["conversation"], send=send, events=stream, utterances=utterances)
    with caplog.at_level("WARNING"):
        down, _ = asyncio.run(run_test(bridge, frames_to_send=[SleepFrame(sleep=0.3)]))
    assert rounds[0] == 2
    assert [f.text for f in down if isinstance(f, TTSSpeakFrame)] == ["[calm]最初の返事。", "[calm]つなぎ直した後の返事。"]
    assert any("reply stream broke (ValueError" in r.getMessage() for r in caplog.records)


# --- 話している途中に言葉が取れた時 -----------------------------------------------------------------------------

def test_words_heard_while_speaking_stop_the_turn_once_until_the_turn_is_sent():
    pytest.importorskip("pipecat")
    from pipecat.tests.utils import SleepFrame, run_test

    sent: list[str] = []
    stops: list[str] = []
    bridge = _bridge(sent, stops=stops)

    async def speak():
        await bridge.heard_words("やっぱり")
        await bridge.heard_words("やっぱりやめ")   # 同じ発話の次の声の区間
    asyncio.run(speak())
    assert stops == ["stop"] and not bridge.wants_words()
    asyncio.run(run_test(bridge, frames_to_send=[_said("やっぱりやめよう"), SleepFrame(sleep=0.2)]))
    assert sent == ["やっぱりやめよう"]
    assert bridge.wants_words()   # 送った後の次の発話では、 また止める


def test_its_own_voice_heard_while_it_is_cut_does_not_stop_the_turn():
    pytest.importorskip("pipecat")
    stops: list[str] = []
    bridge = _bridge([], stops=stops)
    bridge._cut = [{"text": "3 つの箱の結果を表に出した。"}]
    asyncio.run(bridge.heard_words("3つの"))
    assert stops == [] and bridge.wants_words()
    asyncio.run(bridge.heard_words("ちょっと待って"))
    assert stops == ["stop"]


def test_its_own_voice_read_out_from_a_symbol_does_not_stop_the_turn():
    pytest.importorskip("pipecat")
    stops: list[str] = []
    bridge = _bridge([], stops=stops, reading=_reading)
    bridge._cut = [{"text": "±10 は押しても壊れない。"}]
    asyncio.run(bridge.heard_words("プラス"))
    assert stops == [] and bridge.wants_words()
    asyncio.run(bridge.heard_words("ちょっと待って"))
    assert stops == ["stop"]


def test_without_a_way_to_stop_no_words_are_wanted():
    pytest.importorskip("pipecat")
    assert not _bridge([]).wants_words()


def test_the_listener_tries_the_words_while_speaking_until_some_come(monkeypatch):
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import InputAudioRawFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame
    from pipecat.tests.utils import SleepFrame, run_test

    import backend.voice_call.services as services
    monkeypatch.setattr(services, "PEEK_SECS", 0.05)
    answers = ["", "", "やめて"]   # あくびの間は言葉にならず、 3 回目で言葉が取れた

    class Backend:
        tries = 0

        async def transcribe(self, wav: bytes) -> str:
            Backend.tries += 1
            return answers.pop(0) if answers else ""

    heard: list[str] = []

    async def on_words(text: str) -> None:
        heard.append(text)

    async def lost() -> None:
        pass

    stt = services.ListenSTT(Backend(), on_lost=lost, on_words=on_words, wants_words=lambda: not heard)
    audio = InputAudioRawFrame(audio=bytes(320), sample_rate=16000, num_channels=1)
    frames = [VADUserStartedSpeakingFrame(), audio, SleepFrame(sleep=0.4), audio, VADUserStoppedSpeakingFrame(),
              SleepFrame(sleep=0.1)]
    asyncio.run(run_test(stt, frames_to_send=frames))
    assert heard == ["やめて"]
    # 言葉が取れた後は試さない (= 途中の 3 回と、 言い終えた区間の 1 回)
    assert Backend.tries == 4


def test_audio_that_arrives_while_the_app_has_the_microphone_off_is_dropped(caplog):
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import InputAudioRawFrame
    from pipecat.tests.utils import run_test

    from backend.voice_call.services import MicGate

    state = {"on": True}

    class Flip:
        """3 つ目の枠の前に app がマイクを切り、 5 つ目の前に入れ直す。"""
        def __init__(self):
            self.n = 0

        def __call__(self) -> bool:
            self.n += 1
            if self.n == 3:
                state["on"] = False
            if self.n == 5:
                state["on"] = True
            return state["on"]

    audio = [InputAudioRawFrame(audio=bytes([i]) * 320, sample_rate=16000, num_channels=1) for i in range(6)]
    with caplog.at_level("INFO"):
        down, _ = asyncio.run(run_test(MicGate(Flip()), frames_to_send=audio))
    passed = [f.audio[0] for f in down if isinstance(f, InputAudioRawFrame)]
    assert passed == [0, 1, 4, 5]
    lines = [r.getMessage() for r in caplog.records if "microphone" in r.getMessage()]
    assert lines == ["voice call: audio arrives while the app has the microphone off; dropping it",
                     "voice call: the microphone is on again; listening"]


def test_the_listener_leaves_no_try_running_when_the_call_ends_while_speaking(monkeypatch):
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import InputAudioRawFrame, VADUserStartedSpeakingFrame
    from pipecat.tests.utils import SleepFrame, run_test

    import backend.voice_call.services as services
    monkeypatch.setattr(services, "PEEK_SECS", 0.05)

    class Backend:
        async def transcribe(self, wav: bytes) -> str:
            return ""

    async def on_words(text: str) -> None:
        pass

    async def lost() -> None:
        pass

    stt = services.ListenSTT(Backend(), on_lost=lost, on_words=on_words)
    audio = InputAudioRawFrame(audio=bytes(320), sample_rate=16000, num_channels=1)
    # 話し始めたまま (= 言い終えの知らせが来ないまま) 通話が終わる
    asyncio.run(run_test(stt, frames_to_send=[VADUserStartedSpeakingFrame(), audio, SleepFrame(sleep=0.2)]))
    assert stt._peek_task is None


def test_a_call_closed_while_speaking_hands_over_the_sentences_not_yet_said():
    pytest.importorskip("pipecat")
    import time

    from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame
    from pipecat.tests.utils import SleepFrame, run_test

    later = int(time.time() * 1000) + 60_000
    events = [_reply("r1", "1 文目。\n2 文目。\n3 文目。", later)]
    handed: list[dict] = []
    frames = [SleepFrame(sleep=0.2), BotStartedSpeakingFrame(), BotStoppedSpeakingFrame(), BotStartedSpeakingFrame()]
    asyncio.run(run_test(_bridge([], events, on_handover=handed.append), frames_to_send=frames))
    # 鳴っていた 2 文目から (= 鳴り終えた 1 文目は渡さない)
    assert [s["text"] for s in handed[0]["sentences"]] == ["2 文目。", "3 文目。"]
    assert handed[0]["since_ms"] <= int(time.time() * 1000)


def test_a_redialed_call_says_the_handed_over_sentences_and_the_replies_from_the_gap():
    pytest.importorskip("pipecat")
    import time

    from pipecat.frames.frames import TTSSpeakFrame
    from pipecat.tests.utils import SleepFrame, run_test

    now = int(time.time() * 1000)
    resume = {"since_ms": now - 1000, "sentences": [{"mark": "happy", "text": "途切れた文。"}]}
    events = [_reply("before", "閉じる前に鳴った返事。", now - 5000), _reply("gap", "間に届いた返事。", now - 500)]
    down, _ = asyncio.run(run_test(_bridge([], events, resume=resume), frames_to_send=[SleepFrame(sleep=0.2)]))
    assert [f.text for f in down if isinstance(f, TTSSpeakFrame)] == ["[happy]途切れた文。", "[calm]間に届いた返事。"]
