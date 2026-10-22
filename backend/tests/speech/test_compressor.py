"""声の音に掛けるコンプレッサー (= `backend/speech/compressor.py`)。 ffmpeg が在る機械では、 本物の ffmpeg に通す。"""
from __future__ import annotations

import asyncio
import io
import math
import shutil
import struct
import wave

import pytest

from backend.speech import compressor


def _wav(samples: list[float], rate: int = 16_000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, x)) * 32767)) for x in samples))
    return out.getvalue()


def _read(data: bytes) -> tuple[int, list[float]]:
    with wave.open(io.BytesIO(data)) as w:
        raw = w.readframes(w.getnframes())
        return w.getframerate(), [v / 32768 for v in struct.unpack(f"<{len(raw) // 2}h", raw)]


def test_nothing_written_is_no_compressor():
    assert compressor.compressor_settings(None) is None


@pytest.mark.parametrize("broken", [
    "on", [], {"threshold": -18}, {"ratio": "3"}, {"ratio": True},
    {"ratio": 0.5}, {"ratio": 21}, {"threshold_db": 1}, {"threshold_db": -61}, {"attack_ms": 0},
    {"release_ms": 9001}, {"makeup_db": -1}, {"makeup_db": 37}, {"limit_db": 0.5}, {"limit_db": -25},
])
def test_a_compressor_out_of_what_ffmpeg_takes_is_of_the_wrong_shape(broken):
    assert compressor.compressor_settings(broken) is False


def test_the_values_go_to_ffmpeg_as_its_linear_values():
    chain = compressor.filter_chain({"threshold_db": -20, "ratio": 3, "attack_ms": 10, "release_ms": 150,
                                     "makeup_db": 6, "limit_db": -1})
    assert chain == ("acompressor=threshold=0.1:ratio=3:attack=10:release=150:makeup=1.99526,"
                     "alimiter=limit=0.891251:level=disabled")


def test_nothing_but_the_compressor_is_added_when_no_limit_is_written():
    assert compressor.filter_chain({}) == "acompressor"
    assert compressor.filter_chain({"ratio": 4}) == "acompressor=ratio=4"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_ffmpeg_evens_out_loud_and_quiet_parts_and_keeps_the_wav_shape():
    rate = 16_000
    # 大きい所 (= 0.9) と小さい所 (= 0.1) が交互の 440Hz
    tone = [(0.9 if (i // 4000) % 2 == 0 else 0.1) * math.sin(2 * math.pi * 440 * i / rate) for i in range(rate * 2)]
    out_rate, out = _read(asyncio.run(compressor.compress(_wav(tone, rate), {"threshold_db": -24, "ratio": 8})))
    assert out_rate == rate and abs(len(out) - len(tone)) < rate // 100
    loud = max(abs(x) for x in out[2000:3500])
    quiet = max(abs(x) for x in out[6000:7500])
    assert loud / quiet < 0.9 / 0.1          # 山と谷の差が縮んでいる


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_the_limit_holds_the_peaks_below_it():
    rate = 16_000
    tone = [0.99 * math.sin(2 * math.pi * 440 * i / rate) for i in range(rate)]
    _, out = _read(asyncio.run(compressor.compress(_wav(tone, rate), {"ratio": 1, "limit_db": -6})))
    assert max(abs(x) for x in out[rate // 10:]) <= 10 ** (-6 / 20) + 0.01


def test_sound_that_is_not_audio_says_why(monkeypatch):
    if shutil.which("ffmpeg") is None:
        pytest.skip("needs ffmpeg")
    with pytest.raises(compressor.CompressorError, match="ffmpeg failed"):
        asyncio.run(compressor.compress(b"not a wav", {}))


def test_no_ffmpeg_says_so(monkeypatch):
    monkeypatch.setattr(compressor.shutil, "which", lambda name: None)
    with pytest.raises(compressor.CompressorError, match="not on PATH"):
        asyncio.run(compressor.compress(_wav([0.0] * 100), {}))
