"""電話の会話の、 agent の段 (= Pipecat の並びで LLM が居る場所に、 タブの agent を置く)。

行き: 発話のまとめ役 (= Pipecat の user aggregator) が人の 1 回分の発話を渡してくる。 それを、 画面で打った時と
同じ口でそのタブへ送る (= 声で聞いている印は送る口の側で付く)。 言いさし (= 「、」「なんか」 などで終わる) は
送らずに続きを待ち、 続きが来ないまま待ちの時間が過ぎたら送る (= 画面の会話の `turnTaker.js` と同じ決まり)。

帰り: そのタブの agent が書いた返事を、 届いた順に声にする。 人の新しい発話をタブへ送った時点で、 鳴っている声と
まだ鳴らしていない文は捨て、 タブの記録にその発話が載る (= 新しい turn が始まる) までに届いた文は、 前の turn の
物として言わない (= agent が新しい発話を考えている間に、 前の返事の続きが鳴らないように)。 何を声にするかは画面の `listener.js` と同じ決まり
(= 返事の文だけ。 thinking とツールの呼び出しと sub-agent の物は言わない。 会話を始める前の物と、 同じ物の 2 度目は
言わない)。 返事は誰の発話への物でも言う (= 画面から打った文への返事も、 電話で聞ける)。 文の切り分けと言い方の
印は、 画面と同じ backend の口 (= `utterances`) が決める。
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    LLMContextFrame,
    StartFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from backend.voice_call.rules import MAX_HEARD, is_unfinished, marked, speech_of

logger = logging.getLogger(__name__)


class AgentBridge(FrameProcessor):
    """人の発話をタブへ送り、 タブの返事を声の文にして流す。

    conversation                         間の取り方 (= backend の `voice.conversation`)
    send(text) -> 送れたか               そのタブへ 1 通送る
    events() -> そのタブの event の流れ  返事を拾う元
    utterances(text) -> [{mark, text}]   返事の文を、 声にする文の並びにする
    """

    def __init__(self, conversation: dict, *, send: Callable[[str], Awaitable[bool]],
                 events: Callable[[], AsyncIterator[dict]],
                 utterances: Callable[[str], Awaitable[list[dict]]], **kwargs):
        super().__init__(**kwargs)
        self._endings = conversation["unfinished_endings"]
        # 言いさしの後に待つ時間 (= 声が途切れてから wait_ms。 まとめ役が発話を渡すのは pause_ms の無音の後)
        self._hold_secs = max(0.0, (conversation["wait_ms"] - conversation["pause_ms"]) / 1000)
        self._send = send
        self._events = events
        self._utterances = utterances
        self._pending: list[str] = []
        self._hold_task: asyncio.Task | None = None
        self._replies_task: asyncio.Task | None = None
        self._heard: OrderedDict[str, None] = OrderedDict()
        self._since_ms = 0
        # 人の新しい発話を送った後、 タブの記録にその発話が載るまでの間か
        self._awaiting_turn = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            if not self._replies_task:
                self._since_ms = int(time.time() * 1000)
                self._replies_task = self.create_task(self._follow_replies(), "voice-call-replies")
            return
        if isinstance(frame, (EndFrame, CancelFrame)):
            await self._stop()
            await self.push_frame(frame, direction)
            return
        if isinstance(frame, LLMContextFrame):
            # 発話のまとめ役が渡す、 人の 1 回分の発話 (= ここで受け止め、 下流の声の段へは流さない)
            if not frame.speculation:
                await self._said(frame.context)
            return
        if isinstance(frame, UserStartedSpeakingFrame) and self._hold_task:
            # 言いさしの続きを話し始めた: 待ちを止め、 次の発話と合わせて送る
            await self.cancel_task(self._hold_task)
            self._hold_task = None
        await self.push_frame(frame, direction)

    # --- 行き -------------------------------------------------------------------------------------------------

    async def _said(self, context) -> None:
        texts = [_text_of(m) for m in context.get_messages() if m.get("role") == "user"]
        context.set_messages([])
        text = "".join(t for t in texts if t).strip()
        if not text:
            return
        self._pending.append(text)
        if self._hold_task:
            await self.cancel_task(self._hold_task)
            self._hold_task = None
        if is_unfinished("".join(self._pending), self._endings):
            self._hold_task = self.create_task(self._send_after_hold(), "voice-call-hold")
            return
        await self._flush()

    async def _send_after_hold(self) -> None:
        await asyncio.sleep(self._hold_secs)
        self._hold_task = None
        await self._flush()

    async def _flush(self) -> None:
        text = "".join(self._pending)
        self._pending = []
        if text:
            # 前の turn の声は、 ここで全部止める (= 送り終えるまで待たない。 送るのに数秒掛かることがある)
            self._awaiting_turn = True
            await self.broadcast_interruption()
            sent = await self._send(text)
            logger.info("voice call: sent chars=%d ok=%s", len(text), sent)

    # --- 帰り -------------------------------------------------------------------------------------------------

    async def _follow_replies(self) -> None:
        async for event in self._events():
            if event.get("type") == "user_message":
                self._awaiting_turn = False   # 新しい turn が始まった
                continue
            text = self._fresh_speech(event)
            if not text or self._awaiting_turn:
                continue
            for said in await self._utterances(text):
                if self._awaiting_turn:
                    break
                await self.push_frame(TTSSpeakFrame(marked(said.get("mark") or "", said.get("text") or "")))

    def _fresh_speech(self, event: dict) -> str | None:
        found = speech_of(event)
        if found is None:
            return None
        key, text = found
        if key in self._heard:
            return None
        self._heard[key] = None
        while len(self._heard) > MAX_HEARD:
            self._heard.popitem(last=False)
        ts = event.get("ts")
        return text if isinstance(ts, (int, float)) and ts > self._since_ms else None

    async def _stop(self) -> None:
        for task in (self._hold_task, self._replies_task):
            if task:
                await self.cancel_task(task)
        self._hold_task = self._replies_task = None


def _text_of(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text") or "" for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""
