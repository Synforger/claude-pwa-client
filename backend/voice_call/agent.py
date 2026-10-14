"""電話の会話の、 agent の段 (= Pipecat の並びで LLM が居る場所に、 タブの agent を置く)。

行き: 発話のまとめ役 (= Pipecat の user aggregator) が人の 1 回分の発話を渡してくる。 それを、 画面で打った時と
同じ口でそのタブへ送る (= 声で聞いている印は送る口の側で付く)。 言いさし (= 「、」「なんか」 などで終わる) は
送らずに続きを待ち、 続きが来ないまま待ちの時間が過ぎたら送る (= 画面の会話の `turnTaker.js` と同じ決まり)。

帰り: そのタブの agent が書いた返事を、 届いた順に声にする。 人の新しい発話を受け取った時点で前の返事の続きは
言わず、 タブへ送る時点で鳴っている声とまだ鳴らしていない文は捨て、 タブの記録にその発話が載る (= 新しい turn が始まる) までに届いた文は、 前の turn の
物として言わない (= agent が新しい発話を考えている間に、 前の返事の続きが鳴らないように)。 何を声にするかは画面の `listener.js` と同じ決まり
(= 返事の文だけ。 thinking とツールの呼び出しと sub-agent の物は言わない。 会話を始める前の物と、 同じ物の 2 度目は
言わない)。 返事は誰の発話への物でも言う (= 画面から打った文への返事も、 電話で聞ける)。 文の切り分けと言い方の
印は、 画面と同じ backend の口 (= `utterances`) が決める。

小窓: iPhone の app の PiP に出す会話と状態を、 通話の data の通り道 (= RTVI の server-message) で app へ送る。
送るのは `{"pip": "line", "who": "user" | "agent", "text"}` (= タブの発話と返事。 声にしない返事も出す。 会話を
始める前の分は、 タブの記録から直近 PICTURE_HISTORY 行だけを、 記録の読み直しが途切れた所でまとめて送る) と `{"pip": "state", "state": "listening" | "thinking" | "speaking" | "waiting"}` (= 人が話し始めた /
タブへ送った / 声が鳴り始めた / 鳴り終えた)。 描くのは app (= `shell/ios/App/App/CallPicture.swift`)。

声の入 / 切: 画面の 🗣 のボタンで、 返事を声にするかを切り替える (= app が RTVI の client-message `voice-speech`
`{"on": bool}` で知らせる。 始める時は `speech`)。 切の間は返事を声にせず (= 鳴っている声も止める)、 小窓には出す。
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict, deque
from collections.abc import AsyncIterator, Awaitable, Callable

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    CancelFrame,
    EndFrame,
    Frame,
    InterruptionFrame,
    LLMContextFrame,
    StartFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi import RTVIClientMessageFrame, RTVIServerMessageFrame

from backend.voice_call.rules import (
    MAX_HEARD,
    is_unfinished,
    marked,
    shown_reply_text,
    shown_user_text,
    speech_of,
)

logger = logging.getLogger(__name__)

# 小窓に出す、 会話を始める前のタブの会話の行数 (= app の小窓が覚える数と同じ)
PICTURE_HISTORY = 40
# 会話を始める前の会話は、 記録の読み直しがこの間途切れたら、 まとめて送る (= 1 行ずつ送らない)
HISTORY_SETTLE_SECS = 0.3


class AgentBridge(FrameProcessor):
    """人の発話をタブへ送り、 タブの返事を声の文にして流す。

    conversation                         間の取り方 (= backend の `voice.conversation`)
    send(text) -> 送れたか               そのタブへ 1 通送る
    events() -> そのタブの event の流れ  返事を拾う元
    utterances(text) -> [{mark, text, values}]   返事の文を、 声にする文の並びにする
    """

    def __init__(self, conversation: dict, *, send: Callable[[str], Awaitable[bool]],
                 events: Callable[[], AsyncIterator[dict]],
                 utterances: Callable[[str], Awaitable[list[dict]]], speech: bool = True, **kwargs):
        super().__init__(**kwargs)
        self._endings = conversation["unfinished_endings"]
        # 言いさしの後に待つ時間 (= 声が途切れてから wait_ms。 まとめ役が発話を渡すのは pause_ms の無音の後)
        self._hold_secs = max(0.0, (conversation["wait_ms"] - conversation["pause_ms"]) / 1000)
        # 言い終えた発話を送る前に待つ時間 (= この間に話し始めたら、 続きとつなげる)
        self._resume_secs = conversation["resume_ms"] / 1000
        # 送るのは 1 通ずつ、 届いた順に (= 送る処理は割り込みで打ち切られない task で回す)
        self._send_lock = asyncio.Lock()
        self._said_at = 0.0
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
        # 返事を声にするか (= 画面の 🗣)
        self._speech = speech
        # 小窓: 送った行 (= 同じ物を 2 度送らない) と、 会話を始める前の行の溜め
        self._shown: OrderedDict[str, None] = OrderedDict()
        self._history: deque[tuple[str, str]] = deque(maxlen=PICTURE_HISTORY)
        # 小窓へ最後に出した人の発話の親 (= 同じ親の発話が来たら、 その発話を置き換える)
        self._last_user_parent: str | None = None
        self._history_task: asyncio.Task | None = None

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
        if isinstance(frame, RTVIClientMessageFrame):
            # app からの知らせ (= ここで受け止め、 下流へは流さない)
            if frame.type == "voice-speech" and isinstance(frame.data, dict) and isinstance(frame.data.get("on"), bool):
                await self._set_speech(frame.data["on"])
            return
        if isinstance(frame, LLMContextFrame):
            # 発話のまとめ役が渡す、 人の 1 回分の発話 (= ここで受け止め、 下流の声の段へは流さない)
            if not frame.speculation:
                await self._said(frame.context)
            return
        if isinstance(frame, UserStartedSpeakingFrame):
            await self._show_state("listening")
        elif isinstance(frame, BotStartedSpeakingFrame):
            await self._show_state("speaking")
        elif isinstance(frame, BotStoppedSpeakingFrame):
            await self._show_state("waiting")
        if isinstance(frame, UserStartedSpeakingFrame) and self._hold_task:
            # 待っている間に続きを話し始めた: 待ちを止め、 次の発話と合わせて送る
            await self.cancel_task(self._hold_task)
            self._hold_task = None
            logger.info("voice call: resumed %d ms after the turn ended; joined with the next",
                        (time.monotonic() - self._said_at) * 1000)
        await self.push_frame(frame, direction)

    # --- 行き -------------------------------------------------------------------------------------------------

    async def _said(self, context) -> None:
        texts = [_text_of(m) for m in context.get_messages() if m.get("role") == "user"]
        context.set_messages([])
        text = "".join(t for t in texts if t).strip()
        if not text:
            return
        self._pending.append(text)
        self._said_at = time.monotonic()
        # 人が話し終えた時点で、 前の turn の返事の続きは言わない (= 送る前の待ちの間に届いた物も)
        self._awaiting_turn = True
        if self._hold_task:
            await self.cancel_task(self._hold_task)
            self._hold_task = None
        # 言いさしなら続きを wait_ms まで、 言い終えていても resume_ms だけ待つ (= 待つ間に話し始めたら、
        # UserStartedSpeakingFrame で待ちを止め、 次の発話とつなげて送る)
        hold = self._hold_secs if is_unfinished("".join(self._pending), self._endings) else self._resume_secs
        self._hold_task = self.create_task(self._send_after_hold(hold), "voice-call-hold")

    async def _send_after_hold(self, secs: float) -> None:
        if secs > 0:
            await asyncio.sleep(secs)
        self._hold_task = None
        await self._flush()

    async def _flush(self, *, closing: bool = False) -> None:
        """待っている発話を送る。

        ⚠ 送る処理は、 この段の frame の処理 (= process_frame) の中で待たない。 人が話し始めると発話のまとめ役が
        割り込み (= InterruptionFrame) を流し、 Pipecat は処理中の frame の処理を打ち切る。 送っている途中の
        発話はそこで消えていた (= 長く話すと、 途中の間で「言い終えた」 と判定された区間が全部消え、 最後の区間
        だけが届いた)。 ここは待ちの task から呼ばれ、 割り込みでは止まらない。
        """
        text = "".join(self._pending)
        self._pending = []
        if not text:
            return
        # 前の turn の声は、 ここで全部止める (= 送り終えるまで待たない。 送るのに数秒掛かることがある)。 止めるのは
        # 下流 (= 声の段と出口) だけ: broadcast_interruption は、 この段の frame の待ち行列も空にし、 待っている
        # 次の発話を捨てる
        if not closing:
            await self.push_frame(InterruptionFrame())
        async with self._send_lock:
            sent = await self._send(text)
        logger.info("voice call: sent chars=%d ok=%s", len(text), sent)
        if sent and not closing:
            await self._show_state("thinking")

    # --- 帰り -------------------------------------------------------------------------------------------------

    async def _follow_replies(self) -> None:
        async for event in self._events():
            if event.get("type") == "user_message":
                self._awaiting_turn = False   # 新しい turn が始まった
                said = shown_user_text(event.get("text"))
                if said:
                    # claude は取り消した発話を記録に残し、 送り直した発話を同じ親に付ける (= 声の会話は、 途中の間で
                    # 区切られて先に送った前半を取り消し、 後半をつなげて送り直す)。 同じ親なら前の発話を置き換える
                    parent = event.get("parentUuid")
                    replace = parent is not None and parent == self._last_user_parent
                    self._last_user_parent = parent
                    await self._picture_line("user", said, event, event.get("uuid"), replace=replace)
                continue
            found = speech_of(event)
            if found:
                await self._picture_line("agent", shown_reply_text(found[1]), event, found[0])
            text = self._fresh_speech(event)
            if not text or self._awaiting_turn:
                continue
            if not self._speech:
                continue
            for said in await self._utterances(text):
                if self._awaiting_turn or not self._speech:
                    break
                await self.push_frame(TTSSpeakFrame(marked(said.get("mark") or "", said.get("text") or "", said.get("values"))))

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
        return text if self._since(event) else None

    def _since(self, event: dict) -> bool:
        """会話を始めた後の event か (= 前から在った物は、 声にも小窓にも出さない)。"""
        ts = event.get("ts")
        return isinstance(ts, (int, float)) and ts > self._since_ms

    # --- 小窓 -------------------------------------------------------------------------------------------------

    async def _set_speech(self, on: bool) -> None:
        self._speech = on
        if not on:
            await self.push_frame(InterruptionFrame())   # 鳴っている声とまだ鳴らしていない文を止める
        logger.info("voice call: speech %s", "on" if on else "off")

    async def _picture_line(self, who: str, text: str, event: dict, key: str | None, *, replace: bool = False) -> None:
        """タブの 1 行を小窓へ。 会話を始める前の行は溜めて、 読み直しが途切れた所でまとめて送る。

        replace: 小窓の最後の人の発話を、 この行で置き換える (= 取り消された発話の送り直し)。
        """
        key = key or f"{who}:{event.get('ts')}:{text}"
        if not text or key in self._shown:
            return
        self._shown[key] = None
        while len(self._shown) > MAX_HEARD:
            self._shown.popitem(last=False)
        if self._since(event):
            await self._send_history()
            await self._show_line(who, text, replace=replace)
            return
        last_user = next((i for i in range(len(self._history) - 1, -1, -1) if self._history[i][0] == "user"), None)
        if replace and last_user is not None:
            self._history[last_user] = (who, text)
        else:
            self._history.append((who, text))
        if self._history_task:
            await self.cancel_task(self._history_task)
        self._history_task = self.create_task(self._send_history_when_settled(), "voice-call-picture-history")

    async def _send_history_when_settled(self) -> None:
        await asyncio.sleep(HISTORY_SETTLE_SECS)
        self._history_task = None
        await self._send_history()

    async def _send_history(self) -> None:
        if self._history_task:
            await self.cancel_task(self._history_task)
            self._history_task = None
        while self._history:
            who, text = self._history.popleft()
            await self._show_line(who, text)

    async def _show_line(self, who: str, text: str, *, replace: bool = False) -> None:
        if text:
            data = {"pip": "line", "who": who, "text": text}
            if replace:
                data["replace"] = True
            await self.push_frame(RTVIServerMessageFrame(data=data))

    async def _show_state(self, state: str) -> None:
        await self.push_frame(RTVIServerMessageFrame(data={"pip": "state", "state": state}))

    async def _stop(self) -> None:
        for task in (self._hold_task, self._replies_task, self._history_task):
            if task:
                await self.cancel_task(task)
        self._hold_task = self._replies_task = self._history_task = None
        # 待っている間に通話が終わった発話も送る (= 話し終えてすぐ切った時に、 最後の発話を捨てない)
        await self._flush(closing=True)


def _text_of(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text") or "" for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""
