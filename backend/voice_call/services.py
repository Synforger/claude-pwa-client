"""電話の会話の、 聞き取りと声の部品 (= Pipecat の部品の形で、 声の口と同じ engine を呼ぶ)。

聞き取りも声も、 画面の口 (= `routes/voice.py` の `transcribe` / `synthesize`) と同じ関数を通す。 engine の URL・
手がかりの語・言い方の印・コンプレッサーは、 画面で話す時と同じ設定から決まる。
"""
from __future__ import annotations

import io
import wave
from collections.abc import AsyncGenerator

from fastapi import HTTPException
from pipecat.frames.frames import ErrorFrame, Frame, TranscriptionFrame, TTSAudioRawFrame
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.services.tts_service import TTSService
from pipecat.utils.time import time_now_iso8601

from backend.routes.voice import synthesize, transcribe
from backend.voice_call.rules import split_mark

class ListenSTT(SegmentedSTTService):
    """言い終えた区間の声を、 そのタブの聞き取りの engine で文字にする。"""

    def __init__(self, session_id: str, **kwargs):
        super().__init__(**kwargs)
        self._session_id = session_id

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        try:
            text = await transcribe(self._session_id, audio, "audio/wav")
        except HTTPException as error:
            yield ErrorFrame(error=f"listening failed: {error.detail}")
            return
        if text:
            yield TranscriptionFrame(text, self._user_id, time_now_iso8601())


class VoiceTTS(TTSService):
    """1 文を、 その印の言い方で、 そのタブの声の engine で音にする。"""

    def __init__(self, session_id: str, marks: dict, **kwargs):
        super().__init__(push_start_frame=True, push_stop_frames=True, **kwargs)
        self._session_id = session_id
        self._marks = marks

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        mark, text = split_mark(text, self._marks)
        try:
            _, sound = await synthesize(self._session_id, text, mark)
        except HTTPException as error:
            yield ErrorFrame(error=f"speaking failed: {error.detail}")
            return
        with wave.open(io.BytesIO(sound)) as wav:
            rate, channels, pcm = wav.getframerate(), wav.getnchannels(), wav.readframes(wav.getnframes())
        yield TTSAudioRawFrame(audio=pcm, sample_rate=rate, num_channels=channels, context_id=context_id)
