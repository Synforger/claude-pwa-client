"""声の音に掛けるコンプレッサー (= 文の中の強弱を均す)。 ffmpeg の `acompressor` と、 書けば `alimiter` を通す。

声のスタイルによっては、 文の中の山と谷の差が大きく、 平均の大きさが同じでも音量が揃っていないように聞こえる。
文ごとの音 (= engine が返した WAV) に掛け、 WAV で返す。

    "compressor": { "threshold_db": -18, "ratio": 3, "attack_ms": 10, "release_ms": 150, "makeup_db": 6, "limit_db": -1 }

    threshold_db: これより大きい所を縮める (= 既定 -18.06、 ffmpeg の既定 0.125)
    ratio:        縮める比 (= 既定 2)
    attack_ms / release_ms: 縮め始める / 戻す速さ (= 既定 20 / 250)
    makeup_db:    縮めた後に持ち上げる量 (= 既定 0。 縮めると全体が小さくなるので、 戻す時に書く)
    limit_db:     書けば、 最後にこの大きさを超えないように抑える (= 標本の山。 書かなければ抑えない)

書いていない項目は ffmpeg の既定。 値の範囲は ffmpeg が受ける範囲 (= `ffmpeg -h filter=acompressor` / `alimiter`)。
"""
from __future__ import annotations

import asyncio
import math
import shutil
import tempfile
from pathlib import Path


def _db(linear: float) -> float:
    return 20 * math.log10(linear)


# 項目 → (ffmpeg の filter と引数, 下限, 上限, dB で書くか)。 範囲は ffmpeg 8 の値 (= dB の項目は線形の範囲を dB にした物)
_FIELDS = {
    "threshold_db": ("acompressor", "threshold", _db(0.000976563), 0.0, True),
    "ratio": ("acompressor", "ratio", 1.0, 20.0, False),
    "attack_ms": ("acompressor", "attack", 0.01, 2000.0, False),
    "release_ms": ("acompressor", "release", 0.01, 9000.0, False),
    "makeup_db": ("acompressor", "makeup", 0.0, _db(64), True),
    "limit_db": ("alimiter", "limit", _db(0.0625), 0.0, True),
}
# 実測 (= ffmpeg 8、 Apple M2): 1.2 秒の文で 105 ms、 26 秒の文で 76 ms (= 音の長さにほぼよらず、 起動が大半)。
# 待つ上限は、 その 20 倍 (= 機械が混んでいる時も、 落ちた ffmpeg を待ち続けない)。
_SEEN_COMPRESS_SEC = 0.105
TIMEOUT_SEC = _SEEN_COMPRESS_SEC * 20


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def compressor_settings(raw) -> dict | None | bool:
    """設定の `compressor`。 書いていなければ None、 形が違えば False。"""
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) - set(_FIELDS):
        return False
    for key, value in raw.items():
        low, high = _FIELDS[key][2], _FIELDS[key][3]
        if not _is_number(value) or not low <= value <= high:
            return False
    return dict(raw)


def filter_chain(settings: dict) -> str:
    """ffmpeg の `-af` の値 (= 線形の値で渡す。 alimiter の自動の音量合わせは切る)。"""
    args: dict[str, list[str]] = {"acompressor": [], "alimiter": []}
    for key, value in settings.items():
        name, arg, _low, _high, in_db = _FIELDS[key]
        args[name].append(f"{arg}={10 ** (value / 20) if in_db else value:.6g}")
    chain = ["acompressor" + (f"={':'.join(args['acompressor'])}" if args["acompressor"] else "")]
    if args["alimiter"]:
        chain.append(f"alimiter={':'.join(args['alimiter'])}:level=disabled")
    return ",".join(chain)


class CompressorError(Exception):
    pass


async def compress(sound: bytes, settings: dict) -> bytes:
    """WAV を受けて、 コンプレッサーを掛けた WAV (= 16 bit、 同じ標本化の速さ) を返す。 掛けられなければ CompressorError。"""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise CompressorError("ffmpeg is not on PATH")
    # 出力は file に書く (= 標準出力へ書く WAV は、 長さの欄が埋まらない)
    with tempfile.TemporaryDirectory(prefix="voice-compressor-") as folder:
        given, made = Path(folder) / "in.wav", Path(folder) / "out.wav"
        given.write_bytes(sound)
        process = await asyncio.create_subprocess_exec(
            ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(given),
            "-af", filter_chain(settings), "-c:a", "pcm_s16le", str(made),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        try:
            _, error = await asyncio.wait_for(process.communicate(), TIMEOUT_SEC)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise CompressorError(f"ffmpeg did not finish in {TIMEOUT_SEC:.1f}s") from None
        if process.returncode != 0 or not made.exists():
            raise CompressorError(f"ffmpeg failed ({process.returncode}): {error.decode(errors='replace').strip()[:200]}")
        return made.read_bytes()
