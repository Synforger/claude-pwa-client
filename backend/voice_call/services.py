"""電話の会話の、 聞き取りと声の部品 (= Pipecat の部品の形で、 backend の声の口を呼ぶ)。

聞き取りも声も、 画面と同じ backend の口 (= `transcription` / `synthesis`) を通す。 engine の URL・手がかりの語・
言い方の印・コンプレッサーは、 画面で話す時と同じ設定から決まる。
"""
from __future__ import annotations

import io
import wave
from collections.abc import AsyncGenerator, Awaitable, Callable

from pipecat.frames.frames import ErrorFrame, Frame, TranscriptionFrame, TTSAudioRawFrame
from pipecat.services.settings import STTSettings, TTSSettings
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.services.tts_service import TTSService
from pipecat.utils.time import time_now_iso8601

from backend.voice_call.client import BackendClient, ConversationLost
from backend.voice_call.rules import split_mark

# 聞き取りの所要時間の見込み (= Pipecat の既定のまま。 書いておかないと Pipecat が毎回警告を出す)
TTFS_P99_LATENCY_SECS = 1.0


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
        mark, text = split_mark(text, self._marks)
        try:
            sound = await self._backend.synthesize(text, mark)
        except Exception as error:  # noqa: BLE001 (= 1 文の失敗で会話は止めない)
            yield ErrorFrame(error=f"speaking failed: {error}")
            return
        with wave.open(io.BytesIO(sound)) as wav:
            rate, channels, pcm = wav.getframerate(), wav.getnchannels(), wav.readframes(wav.getnframes())
        yield TTSAudioRawFrame(audio=pcm, sample_rate=rate, num_channels=channels, context_id=context_id)
