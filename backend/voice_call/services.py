"""電話の会話の、 聞き取りと声の部品 (= Pipecat の部品の形で、 backend の声の口を呼ぶ)。

聞き取りも声も、 画面と同じ backend の口 (= `transcription` / `synthesis`) を通す。 engine の URL・手がかりの語・
言い方の印・コンプレッサーは、 画面で話す時と同じ設定から決まる。
"""
from __future__ import annotations

import asyncio
import io
import logging
import wave
from dataclasses import dataclass
from collections.abc import AsyncGenerator, Awaitable, Callable

import numpy as np
from pipecat.frames.frames import (
    ErrorFrame,
    Frame,
    InputAudioRawFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.settings import STTSettings, TTSSettings
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.services.tts_service import TTSService
from pipecat.utils.time import time_now_iso8601

from backend.voice_call.client import BackendClient, ConversationLost
from backend.voice_call.rules import split_mark

# 声を作っている間に、 待っていると知らせる回数 (= Pipecat が待つのをやめるまでの時間に何回知らせるか)
KEEPALIVES_PER_TIMEOUT = 3

logger = logging.getLogger(__name__)

# 聞き取りの所要時間の見込み (= Pipecat の既定のまま。 書いておかないと Pipecat が毎回警告を出す)
TTFS_P99_LATENCY_SECS = 1.0


@dataclass
class Volume:
    """その端末の、 声の大きさの倍率 (= 端末の画面のつまみ。 0 〜 2、 1 で engine の音のまま)。 通話中に変わる。

    掛けるのは声を作る時ではなく、 送り口へ渡す時 (= pipeline の `scale_output`)。 返事の文は話し終えるより先に全部
    作られるので、 作る時に掛けると、 話している途中に動かしたつまみはその返事に効かない。
    """
    value: float = 1.0


def scaled(pcm: bytes, gain: float) -> bytes:
    """16 bit の音に倍率を掛ける (= 上限を超えた所は上限で止める)。"""
    if gain == 1.0:
        return pcm
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) * gain
    return np.clip(samples, -32768, 32767).astype(np.int16).tobytes()


class MicGate(FrameProcessor):
    """app がマイクを切っている間に届いた音を、 聞き取りの手前で捨てる (= 切っている間は聞き取りも送信もしない)。

    app はマイクを切ると、 その音の track を止め、 切ったことを WebRTC の知らせ (= `trackStatus`) で backend へ送る。
    Pipecat の受け口はその知らせを映像にしか効かせず、 音は届けば流す。 iPhone の側で音がまた流れ出すと (= 切った
    まま app を前に出した後に、 外の放送が発話として届いた)、 切っているはずの声が聞き取られていた。 ここで知らせの
    通りに捨てる。 切っている間に音が届き始めた時と、 また入った時は、 log に出す。

    microphone_on() -> マイクが入っているか   (= 受け口の音の track の状態。 知らせが来る前は入)
    """

    def __init__(self, microphone_on: Callable[[], bool], **kwargs):
        super().__init__(**kwargs)
        self._microphone_on = microphone_on
        self._dropping = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            on = self._microphone_on()
            if on == self._dropping:
                self._dropping = not on
                logger.info("voice call: %s", "audio arrives while the app has the microphone off; dropping it"
                            if self._dropping else "the microphone is on again; listening")
            if self._dropping:
                return
        await self.push_frame(frame, direction)


class ListenSTT(SegmentedSTTService):
    """言い終えた区間の声を、 backend の聞き取りの口で文字にする。 別の画面が会話を開いたら on_lost を呼ぶ。"""

    def __init__(self, backend: BackendClient, on_lost: Callable[[], Awaitable[None]], **kwargs):
        super().__init__(settings=STTSettings(model=None, language=None),
                         ttfs_p99_latency=TTFS_P99_LATENCY_SECS, **kwargs)
        self._backend = backend
        self._on_lost = on_lost

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        try:
            text = await self._backend.transcribe(audio)
        except ConversationLost:
            await self._on_lost()
            return
        except Exception as error:  # noqa: BLE001 (= 1 回分の聞き取りの失敗で会話は止めない)
            yield ErrorFrame(error=f"listening failed: {error}")
            return
        if text:
            yield TranscriptionFrame(text, self._user_id, time_now_iso8601())


class VoiceTTS(TTSService):
    """1 文を、 その印の言い方で、 backend の声の口で音にする。"""

    def __init__(self, backend: BackendClient, marks: list[str], **kwargs):
        super().__init__(settings=TTSSettings(model=None, voice=None, language=None),
                         push_start_frame=True, push_stop_frames=True, **kwargs)
        self._backend = backend
        self._marks = set(marks)

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        mark, values, text = split_mark(text, self._marks)
        # 声を作っている間は、 その文を待っていると Pipecat に知らせ続ける (= Pipecat は 1 文の音を
        # stop_frame_timeout_s (= 既定 3 秒) で待つのをやめ、 「音が無いまま終わった」 の error を出す。 長い文は作るのに
        # それより掛かる: 2026-10-14 に 90 文字の文が 3.3 秒掛かり、 その error で通話が切れた)
        synthesis = asyncio.ensure_future(self._backend.synthesize(text, mark, values))
        try:
            while not synthesis.done():
                await asyncio.wait({synthesis}, timeout=self._stop_frame_timeout_s / KEEPALIVES_PER_TIMEOUT)
                if not synthesis.done():
                    self._refresh_audio_context(context_id)
            sound = synthesis.result()
        except asyncio.CancelledError:
            synthesis.cancel()
            raise
        except Exception as error:  # noqa: BLE001 (= 1 文の失敗で会話は止めない)
            yield ErrorFrame(error=f"speaking failed: {error}")
            return
        with wave.open(io.BytesIO(sound)) as wav:
            rate, channels, pcm = wav.getframerate(), wav.getnchannels(), wav.readframes(wav.getnframes())
        yield TTSAudioRawFrame(audio=pcm, sample_rate=rate, num_channels=channels, context_id=context_id)
