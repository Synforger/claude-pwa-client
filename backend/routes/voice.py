"""声の口: agent の返事を、 音声合成の engine で音にして返す。

声を持つかどうかは agent の設定 (= `agents.<id>.voice`) が決める。 書いていない agent のタブは声を持たない。

    "voice": {
      "engine":  "http://127.0.0.1:10101",
      "speaker": 888753760,
      "query":   { "prePhonemeLength": 0.05 },
      "marks": {
        "calm":  { "speedScale": 1.1 },
        "happy": { "speedScale": 1.15, "tempoDynamicsScale": 1.3 }
      },
      "default": "calm",
      "listen":  { "engine": "http://127.0.0.1:10102", "prompt": "Claude、PWA。", "turn": "/path/to/smart-turn.onnx" },
      "conversation": { "pause_ms": 700, "wait_ms": 3000 },
      "compressor": { "threshold_db": -18, "ratio": 3, "makeup_db": 6, "limit_db": -1 },
      "tuning":  "/path/to/agent/voice.json"
    }

    engine:  VOICEVOX と同じ口 (= `POST /audio_query` と `POST /synthesis`) を持つ engine の URL
    speaker: 声の番号 (= engine が `GET /speakers` で出す style の id)
    query:   どの文にも当てる値 (= engine が問い合わせに返す値のうち、 同じ名前の物を上書きする)
    marks:   言い方の印。 名前 → その印の文に当てる値。 `speaker` を書いた印は、 その文だけ別の声の番号で言う
    default: 印の無い文の印 (= 省けば最初の印)
    listen:  人の声を聞き取る engine (= 省けば聞き取らない)。 whisper.cpp の `whisper-server` と同じ口
             (= `POST /inference`) を持つ engine の URL と、 聞き取りの手がかりにする語 (= 省略可) と、 言い終えたかを
             判定する Smart Turn の model の file (= 省略可。 画面がこの口から受け取って、 画面の中で判定する)
    conversation: 話して送る会話の間の取り方 (= 省略可。 項目は CONVERSATION_DEFAULTS)
    compressor: 文ごとの音に掛けるコンプレッサー (= 省略可。 書かなければ掛けない。 項目は backend/core/compressor.py)
    tuning:  声の調整の file (= 省略可)。 TUNABLE の項目を JSON で書き、 ここの値の上に重ねる。 毎回読むので、
             書き換えれば次の文から効く (= agent が自分の声を調整する置き場。 engine の URL はここに置かない)

返事の流れは 2 段。 画面は返事の文を `utterances` へ渡して声にする文の並びを受け取り、 1 文ずつ `synthesis`
へ渡して音を受け取る (= 1 文目の音が出来た時点で鳴らし始められる。 engine は文の途中の音を返さない)。

    1. POST /sessions/{sid}/voice/utterances    返事の文 → 声にする文と、 その印
    2. POST /sessions/{sid}/voice/synthesis     1 文と印 → 音 (= audio/wav)

人の声は、 画面が声の区切り (= 言い終えた所) を見つけて、 その音を渡し、 聞き取った文を受け取る (= 送るのは画面が
普段の送信口で行う)。 声の区切りを見つけるのは画面の中 (= 声の区間の検出と Smart Turn) で、 backend は model の
file を配るだけ。 会話を開いていられる画面は 1 つのタブに 1 つ (= 後から開いた画面が持ち、 前の画面の音は断る)。

    3. POST   /sessions/{sid}/voice/transcription  録った音 → 聞き取った文
       POST   /sessions/{sid}/voice/interruption   話している途中に言葉が取れた → 実行中の turn を止める
    4. GET    /sessions/{sid}/voice/turn-model     Smart Turn の model の file
    5. POST   /sessions/{sid}/voice/conversation   この画面で会話を開く (= 前の画面から持ち主を移す)
       DELETE /sessions/{sid}/voice/conversation   会話を閉じる

何を声にするか (= コードや path を飛ばし、 文に切り、 印を剥がす) は `backend/core/speech.py` が持つ。
ここが持つのは、 どのタブが声を持つか・engine へ渡す値・失敗の返し方。
"""
from __future__ import annotations

import asyncio
import http.client
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, Response

import backend.config as _config
from backend.core.compressor import CompressorError, compress, compressor_settings
from backend.core.speech import MARK_NAME, MUTE_MARK, mark_values, speakable, utterances
from backend.errors import raise_error
from backend.state import sessions_meta

logger = logging.getLogger(__name__)
router = APIRouter()

# 実測 (= agent の実物の返事 448 本): 返事 1 本は最長 2,623 文字、 声にする 1 文は最長 287 文字
# (= 5,657 文の 99% は 87 文字以下)。 上限は、 実物を通したうえで、 桁の違う入力を engine へ渡さないための物。
_SEEN_REPLY_CHARS = 2_623
_SEEN_UTTERANCE_CHARS = 287
MAX_REPLY_CHARS = _SEEN_REPLY_CHARS * 10
MAX_UTTERANCE_CHARS = _SEEN_UTTERANCE_CHARS * 2
# 実測 (= engine 1.2.0、 GPU なし): 38 文字の合成に 3.2 秒。 engine を待つ上限は、 一番長い 1 文に掛かる
# 時間の 2 倍 (= 2 段のどちらにも同じ値を使う)。
_SEEN_SYNTHESIS_SEC_PER_CHAR = 3.2 / 38
ENGINE_TIMEOUT_SEC = MAX_UTTERANCE_CHARS * _SEEN_SYNTHESIS_SEC_PER_CHAR * 2

# 1 回に録る長さは、 画面で 🎙 を押している間 (= 離した所で終わり) で、 画面は区切らない。 backend が受ける音の
# 上限は、 10 分話し続けた音 (= 1 回の発話として普段まず当たらない長さ) を、 ブラウザが宣言する最大の bitrate
# (= 実測 192 kbps。 WebKit の mp4/AAC。 Chromium の webm/opus は 128 kbps) で録った大きさの 2 倍。
MAX_LISTEN_SEC = 10 * 60
_SEEN_RECORDING_BITS_PER_SEC = 192_000
MAX_AUDIO_BYTES = int(MAX_LISTEN_SEC * _SEEN_RECORDING_BITS_PER_SEC / 8 * 2)
# 実測 (= whisper.cpp 1.9.2 + large-v3-turbo の q5_0、 Apple M2): 124 秒の音の聞き取りに 7.7 秒 (= 形式の変換込み)。
# engine を待つ上限は、 上限の長さの音に掛かる時間の 2 倍。
_SEEN_LISTEN_SEC_PER_AUDIO_SEC = 7.7 / 124
LISTEN_TIMEOUT_SEC = MAX_LISTEN_SEC * _SEEN_LISTEN_SEC_PER_AUDIO_SEC * 2

# 会話の間の取り方の既定 (= 設定か調整の file の `conversation` で変える)。
#   pause_ms:  声が途切れてから、 言い終えたかの判定に入るまでの無音。 語と語の間の息継ぎで判定しない長さ
#              (= Pipecat の既定は 0.2 秒。 考えながら話すと、 語の間がそれより長く空く)
#   wait_ms:   言い終えていないと判定した時に、 送るまで待つ無音 (= 声が途切れた時から数える。 Pipecat の既定)
#   unfinished_endings: 聞き取った文がこれで終わる時は、 言い終えた判定でも送らずに wait_ms まで待つ
#              (= 読点と、 考えている間に出る語。 文末の句点は外して見る)
#   resume_ms: 言い終えたと判定した後、 送る前に待つ無音。 この間に話し始めたら、 続きとつなげて 1 つの発話にする
#              (= Smart Turn は長い発話の途中の間でも「言い終えた」 と出すことがある。 0 なら待たずに送る。
#              既定は声の agent の頼みの値)
#   interrupt: 返事が鳴っている間も聞き、 話し始めたら返事を止める (= false なら、 鳴っている間は聞かない)
CONVERSATION_DEFAULTS = {
    "pause_ms": 700,
    "wait_ms": 3000,
    "resume_ms": 400,
    "unfinished_endings": ["、", ",", "，", "…", "...", "なんか", "えーと", "えっと", "えー", "あのー", "あの",
                           "うーん", "まあ", "その"],
    "interrupt": True,
}
# 調整の file に書ける項目 (= 声と間の取り方。 engine の URL と聞き取りは設定にだけ書く)
TUNABLE = ("speaker", "query", "marks", "default", "conversation", "compressor")

_MARK_NAME = re.compile(MARK_NAME)
# 形の違う `voice` を書いた agent (= 1 度だけ log に出す)。
_warned: set[str] = set()


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_speaker(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _values(raw) -> dict | None:
    """名前 → 数 の組 (= engine の問い合わせの値への上書き)。 形が違えば None。"""
    if not isinstance(raw, dict):
        return None
    return dict(raw) if all(isinstance(k, str) and _is_number(v) for k, v in raw.items()) else None


def _mark(raw) -> dict | None:
    """印 1 つの値の組。 `speaker` は声の番号で、 残りは上書きの値。 形が違えば None。"""
    if not isinstance(raw, dict):
        return None
    if "speaker" in raw and not _is_speaker(raw["speaker"]):
        return None
    return dict(raw) if _values({k: v for k, v in raw.items() if k != "speaker"}) is not None else None


def _is_url(value) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def _is_ms(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _conversation(raw) -> dict | None:
    """会話の間の取り方 (= 書いていない項目は既定)。 形が違えば None。"""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict) or set(raw) - set(CONVERSATION_DEFAULTS):
        return None
    out = {**CONVERSATION_DEFAULTS, **raw}
    endings = out["unfinished_endings"]
    if not (_is_ms(out["pause_ms"]) and _is_ms(out["wait_ms"]) and out["wait_ms"] > out["pause_ms"]):
        return None
    resume = out["resume_ms"]
    if not (isinstance(resume, int) and not isinstance(resume, bool) and resume >= 0):
        return None
    if not isinstance(endings, list) or not all(isinstance(e, str) and e.strip() for e in endings):
        return None
    if not isinstance(out["interrupt"], bool):
        return None
    return {**out, "unfinished_endings": list(endings)}


def _listen(raw) -> dict | None | bool:
    """聞き取りの設定。 書いていなければ None、 形が違えば False。"""
    if raw is None:
        return None
    if not isinstance(raw, dict) or not _is_url(raw.get("engine")):
        return False
    prompt, turn = raw.get("prompt", ""), raw.get("turn", "")
    if not isinstance(prompt, str) or not isinstance(turn, str):
        return False
    return {"engine": raw["engine"].rstrip("/"), "prompt": prompt, "turn": turn}


def voice_settings(raw) -> dict | None:
    """agent の設定の `voice` を、 使える形にして返す。 形の違う設定は「声なし」 (= None)。"""
    if not isinstance(raw, dict):
        return None
    engine, speaker = raw.get("engine"), raw.get("speaker")
    if not _is_url(engine) or not _is_speaker(speaker):
        return None
    listen = _listen(raw.get("listen"))
    if listen is False:
        return None
    query, marks = _values(raw.get("query", {})), raw.get("marks", {})
    if query is None or not isinstance(marks, dict):
        return None
    if not all(isinstance(name, str) and _MARK_NAME.fullmatch(name) and _mark(value) is not None
               for name, value in marks.items()):
        return None
    default = raw.get("default", next(iter(marks), ""))
    if not isinstance(default, str) or (default not in marks if marks else default != ""):
        return None
    conversation, tuning = _conversation(raw.get("conversation")), raw.get("tuning", "")
    if conversation is None or not isinstance(tuning, str):
        return None
    compressor = compressor_settings(raw.get("compressor"))
    if compressor is False:
        return None
    return {"engine": engine.rstrip("/"), "speaker": speaker, "query": query,
            "marks": {name: dict(value) for name, value in marks.items()}, "default": default, "listen": listen,
            "conversation": conversation, "compressor": compressor, "tuning": tuning}


# 調整の file を読んだ結果 (= path → (更新時刻と大きさ, 値, 読めなかった理由))。 変わった時だけ読み直す。
_tuning_files: dict[str, tuple[tuple[int, int], dict, str]] = {}
# log に出した、 調整の file を使えない理由 (= path → 理由。 変わった時だけ出す)
_tuning_logged: dict[str, str] = {}


def _tuning_file(path: str) -> tuple[dict, str]:
    """調整の file の値と、 使えない理由 (= 使えれば空文字)。"""
    file = Path(path).expanduser()
    try:
        stat = file.stat()
    except OSError:
        return {}, "調整の file がありません"
    stamp = (stat.st_mtime_ns, stat.st_size)
    cached = _tuning_files.get(path)
    if cached and cached[0] == stamp:
        return cached[1], cached[2]
    values, error = {}, ""
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        error = f"調整の file を JSON として読めません ({exc})"
    else:
        if not isinstance(data, dict):
            error = "調整の file は JSON の object で書きます"
        elif unknown := sorted(set(data) - set(TUNABLE)):
            error = f"調整の file に書けない項目があります: {', '.join(unknown)} (= 書けるのは {', '.join(TUNABLE)})"
        else:
            values = data
    _tuning_files[path] = (stamp, values, error)
    return values, error


def _tuned(raw: dict, settings: dict) -> tuple[dict, str]:
    """設定の値に調整の file の値を重ねる。 file を使えない時は、 設定の値のままと、 その理由を返す。"""
    path = settings["tuning"]
    values, error = _tuning_file(path)
    if values:
        tuned = voice_settings({**raw, **values})
        if tuned is None:
            error = "調整の file の値の形が違います (= 声の番号は整数、 値は数、 既定の印は marks の名前、 など)"
        else:
            settings = tuned
    if error and _tuning_logged.get(path) != error:
        logger.warning("voice: %s: %s; the backend setting is used", path, error)
    _tuning_logged[path] = error
    return settings, error


def _settings_of(session_id: str) -> dict | None:
    """そのタブの agent の声の設定。 声を持たなければ None。 タブが無ければ 404。"""
    meta = sessions_meta.get(session_id)
    if meta is None:
        raise_error(404, "voice_unknown_session", f"タブが見つかりません: {session_id}", session=session_id)
    raw = (_config.AGENTS.get(meta.agent_id) or {}).get("voice")
    settings = voice_settings(raw)
    if raw is not None and settings is None and meta.agent_id not in _warned:
        _warned.add(meta.agent_id)
        logger.warning("voice: agent=%s has a voice setting of the wrong shape; it has no voice", meta.agent_id)
    if settings is None:
        return None
    settings, error = _tuned(raw, settings) if settings["tuning"] else (settings, "")
    return {**settings, "tuning_error": error}


# 会話を開いている画面 (= タブの id → 画面が名乗った名前)。 backend を再起動すると忘れる (= 次に音を送った画面が
# 持ち主になる)。
_conversations: dict[str, str] = {}
CONVERSATION_HEADER = "X-Voice-Conversation"
_CLIENT_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _listening(session_id: str) -> dict:
    """そのタブの聞き取りの設定。 声を持たなければ 409 voice_not_enabled、 聞き取らなければ 409。"""
    listen = _enabled(session_id)["listen"]
    if not listen:
        raise_error(409, "voice_listen_not_enabled", "このタブの agent は声を聞き取りません")
    return listen


async def _client_of(request: Request) -> str:
    try:
        body = await request.json()
    except ValueError:
        body = None
    client = body.get("client") if isinstance(body, dict) else None
    if not isinstance(client, str) or not _CLIENT_NAME.fullmatch(client):
        raise_error(400, "voice_bad_request", "本文に client (= 英数字と - _ の 64 文字まで) が要ります")
    return client


def _enabled(session_id: str) -> dict:
    settings = _settings_of(session_id)
    if settings is None:
        raise_error(409, "voice_not_enabled", "このタブの agent は声を持っていません")
    return settings


async def _text_of(request: Request) -> tuple[str, dict]:
    """本文の `text` と、 本文そのもの。"""
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or not isinstance(body.get("text"), str):
        raise_error(400, "voice_bad_request", "本文に text (= 文字列) が要ります")
    return body["text"], body


def _post(url: str, data: bytes, content_type: str, timeout: float) -> tuple[int, str, bytes]:
    """engine へ 1 回 POST して (HTTP の状態, 返った物の種類, 中身) を返す。 繋がらなければ OSError、 応答の途中で
    切れれば http.client.HTTPException。"""
    request = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": content_type})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (= url は設定の物)
            return response.status, response.headers.get_content_type(), response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get_content_type(), error.read()


def _call_engine(url: str, body: dict | None, timeout: float) -> tuple[int, str, bytes]:
    """音声合成の engine を 1 回呼ぶ (= 本文は JSON)。"""
    data = json.dumps(body).encode("utf-8") if body is not None else b""
    return _post(url, data, "application/json", timeout)


def _call_listener(url: str, fields: dict[str, str], audio: bytes, audio_type: str,
                   timeout: float) -> tuple[int, str, bytes]:
    """聞き取りの engine を 1 回呼ぶ (= 本文は multipart/form-data。 音は `file`、 残りは文字の欄)。"""
    boundary = f"voice-{uuid.uuid4().hex}"
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
             for name, value in fields.items()]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech"\r\n'
                 f"Content-Type: {audio_type}\r\n\r\n".encode("utf-8") + audio + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return _post(url, b"".join(parts), f"multipart/form-data; boundary={boundary}", timeout)


async def _engine(step: str, url: str, body: dict | None) -> tuple[str, bytes]:
    """engine の 1 段を呼ぶ。 繋がらない・断られた時は、 どの段かを付けて 502 にする。"""
    try:
        status, kind, raw = await asyncio.to_thread(_call_engine, url, body, ENGINE_TIMEOUT_SEC)
    except (OSError, http.client.HTTPException) as error:
        logger.warning("voice: engine could not be reached step=%s: %r", step, error)
        raise_error(502, "voice_engine_unreachable", "音声合成の engine に繋がりません")
    if status != 200:
        _engine_failed(step, status)
    return kind, raw


def _engine_failed(step: str, status: int) -> None:
    logger.warning("voice: engine failed step=%s status=%s", step, status)
    raise_error(502, "voice_engine_failed", f"音声合成の engine が失敗しました ({step}: {status})",
                step=step, status=status)


@router.get("/sessions/{session_id}/voice")
async def get_voice(session_id: str) -> dict:
    """そのタブが声を持つかと、 言い方の印の一覧と、 会話の間の取り方。"""
    settings = _settings_of(session_id)
    if settings is None:
        return {"enabled": False, "marks": [], "default": "", "listen": False, "turn": False,
                "conversation": None, "tuning_error": ""}
    listen = settings["listen"]
    # 印の一覧には予約の印も入れる (= 画面は、 この一覧の印を吹き出しから隠す)
    marks = [*settings["marks"], *([] if MUTE_MARK in settings["marks"] else [MUTE_MARK])]
    return {"enabled": True, "marks": marks, "default": settings["default"],
            "listen": bool(listen), "turn": bool(listen and listen["turn"]),
            "conversation": settings["conversation"], "tuning_error": settings["tuning_error"]}


@router.post("/sessions/{session_id}/voice/utterances")
async def post_utterances(request: Request, session_id: str) -> dict:
    """返事の文を、 声にする文の並びにして返す (= 声にする物が無ければ空の並び)。

    body:
        text (str): agent の返事の文 (= markdown のまま)
    """
    settings = _enabled(session_id)
    text, _ = await _text_of(request)
    if len(text) > MAX_REPLY_CHARS:
        raise_error(413, "voice_text_too_long", f"文が長すぎます (上限 {MAX_REPLY_CHARS} 文字)", limit=MAX_REPLY_CHARS)
    dropped: list[str] = []
    said = utterances(text, settings["marks"], settings["default"], dropped)
    if dropped:
        logger.info("voice: session=%s mark values not used: %s", session_id, ", ".join(dropped))
    return {"utterances": [{"mark": u.mark, "text": u.text, "values": u.values} for u in said]}


@router.post("/sessions/{session_id}/voice/synthesis")
async def post_synthesis(request: Request, session_id: str) -> Response:
    """1 文を、 印の言い方で音にして返す。

    body:
        text (str): 声にする 1 文 (= `utterances` が返した文)
        mark (str, 省略可): 言い方の印 (= 省けば既定の印)
        values (object, 省略可): 印に添えた値 (= `utterances` が返した値。 名前 → 数)
    """
    text, body = await _text_of(request)
    name, values = body.get("mark"), body.get("values")
    if name is not None and not isinstance(name, str):
        raise_error(400, "voice_bad_request", "mark は文字列で渡します")
    if values is not None and not isinstance(values, dict):
        raise_error(400, "voice_bad_request", "values は名前 → 数の組で渡します")
    kind, sound = await synthesize(session_id, text, name, values)
    return Response(content=sound, media_type=kind, headers={"Cache-Control": "no-store"})


async def synthesize(session_id: str, text: str, mark: str | None = None,
                     values: dict | None = None) -> tuple[str, bytes]:
    """1 文を、 印の言い方で音にする (= 画面の口と、 電話の会話が使う)。 返すのは (Content-Type, 音)。

    mark を省けば既定の印。 values は印に添えた値で、 印の値の上に重ねる (= 名前の違う物と範囲の外の物は
    使わない。 core/speech.py の mark_values)。 文の形と印が違えば、 画面の口と同じ形の error を投げる。
    """
    settings = _enabled(session_id)
    name = settings["default"] if mark is None else mark
    if name and name not in settings["marks"]:
        raise_error(400, "voice_unknown_mark", f"この agent に無い印です: {name}", mark=name)
    text = text.strip()
    if not speakable(text):
        raise_error(400, "voice_nothing_to_say", "声にする文字がありません")
    if len(text) > MAX_UTTERANCE_CHARS:
        raise_error(413, "voice_text_too_long", f"文が長すぎます (上限 {MAX_UTTERANCE_CHARS} 文字)",
                    limit=MAX_UTTERANCE_CHARS)

    added, dropped = mark_values(values)
    if dropped:
        logger.info("voice: session=%s mark values not used: %s", session_id, ", ".join(dropped))
    values = {**settings["marks"].get(name, {}), **added}
    speaker = values.pop("speaker", settings["speaker"])
    started = time.monotonic()
    asked = urllib.parse.urlencode({"speaker": speaker, "text": text}, quote_via=urllib.parse.quote)
    kind, raw = await _engine("audio_query", f"{settings['engine']}/audio_query?{asked}", None)
    try:
        query = json.loads(raw)
    except ValueError:
        query = None
    if not isinstance(query, dict):
        _engine_failed("audio_query", 200)
    # 共通の値の上に印の値を当てる。 engine が返した値に無い名前は送らない (= engine の版で名前が変わる)。
    for key, value in {**settings["query"], **values}.items():
        if key in query:
            query[key] = value
    _keep_pauses(query)
    kind, sound = await _engine("synthesis", f"{settings['engine']}/synthesis?speaker={speaker}", query)
    if not kind.startswith("audio/"):
        _engine_failed("synthesis", 200)
    if settings["compressor"] is not None:   # 空の {} も「既定の値で掛ける」
        sound = await _compressed(sound, settings["compressor"])
    logger.info("voice: session=%s mark=%s%s chars=%d bytes=%d ms=%d", session_id, name or "-",
                "".join(f" {k}={v}" for k, v in added.items()), len(text), len(sound),
                (time.monotonic() - started) * 1000)
    return kind, sound


@router.post("/sessions/{session_id}/voice/reading")
async def post_reading(request: Request, session_id: str) -> dict:
    """1 文の読み (= engine が声にする時の拍のカナ) を返す。

    body:
        text (str): 読みにする文
    """
    text, _ = await _text_of(request)
    return {"reading": await reading(session_id, text)}


async def reading(session_id: str, text: str) -> str:
    """1 文を engine が声にする時の読み (= 拍のカナをつなげた物。 間の無音は含めない)。 書いた文字と声がずれる所
    (= 記号・英字・数字) も、 声のとおりに比べられる。 文の形が違えば、 声にする時と同じ error を投げる。"""
    settings = _enabled(session_id)
    text = text.strip()
    if not speakable(text):
        raise_error(400, "voice_nothing_to_say", "声にする文字がありません")
    if len(text) > MAX_UTTERANCE_CHARS:
        raise_error(413, "voice_text_too_long", f"文が長すぎます (上限 {MAX_UTTERANCE_CHARS} 文字)",
                    limit=MAX_UTTERANCE_CHARS)
    asked = urllib.parse.urlencode({"speaker": settings["speaker"], "text": text}, quote_via=urllib.parse.quote)
    _, raw = await _engine("audio_query", f"{settings['engine']}/audio_query?{asked}", None)
    try:
        query = json.loads(raw)
    except ValueError:
        query = None
    if not isinstance(query, dict):
        _engine_failed("audio_query", 200)
    return "".join(
        mora.get("text") or ""
        for phrase in query.get("accent_phrases") or [] if isinstance(phrase, dict)
        for mora in phrase.get("moras") or [] if isinstance(mora, dict))


# log に出した、 コンプレッサーを掛けられなかった理由 (= 同じ理由は 1 度だけ出す)
_compressor_logged: set[str] = set()


async def _compressed(sound: bytes, compressor: dict) -> bytes:
    """コンプレッサーを掛けた音。 掛けられなければ、 engine の音のまま (= 声は止めない) で log に理由を出す。"""
    try:
        return await compress(sound, compressor)
    except CompressorError as error:
        if str(error) not in _compressor_logged:
            _compressor_logged.add(str(error))
            logger.warning("voice: the compressor was skipped: %s", error)
        return sound


# 文の前後の無音 (= 秒)。 engine は無音も話す速さで縮める (= 実測、 AivisSpeech Engine 1.2.0: speedScale 1.5 で 2/3、
# 2.0 で 1/2)。 速さを変えても文の間が詰まらないように、 速さを掛けて渡す (= 書いた秒数のまま空く)。
_PAUSES = ("prePhonemeLength", "postPhonemeLength")


def _keep_pauses(query: dict) -> None:
    speed = query.get("speedScale")
    if not _is_number(speed) or speed <= 0:
        return
    for key in _PAUSES:
        if _is_number(query.get(key)):
            query[key] = query[key] * speed


@router.post("/sessions/{session_id}/voice/transcription")
async def post_transcription(request: Request, session_id: str) -> dict:
    """録った音を聞き取って、 その文を返す (= 声が聞き取れなければ空の文)。

    body: 録った音そのもの (= Content-Type は audio/… 。 形式の変換は engine が行う)
    header: X-Voice-Conversation (省略可) = 会話を開いた画面の名前。 持ち主でない画面の音は断る
    """
    _listening(session_id)   # 声を聞き取らないタブは、 音を読む前に断る
    client = request.headers.get(CONVERSATION_HEADER, "")
    if client and _conversations.setdefault(session_id, client) != client:
        raise_error(409, "voice_conversation_elsewhere", "このタブの会話は、 別の画面で開かれています")
    audio_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if not audio_type.startswith("audio/"):
        raise_error(400, "voice_bad_request", "本文は録った音 (= Content-Type が audio/…) で渡します")
    declared_size = request.headers.get("content-length", "")
    if declared_size.isdigit() and int(declared_size) > MAX_AUDIO_BYTES:
        raise_error(413, "voice_audio_too_large", f"音が大きすぎます (上限 {MAX_AUDIO_BYTES} バイト)",
                    limit=MAX_AUDIO_BYTES)
    audio = await request.body()
    if len(audio) > MAX_AUDIO_BYTES:
        raise_error(413, "voice_audio_too_large", f"音が大きすぎます (上限 {MAX_AUDIO_BYTES} バイト)",
                    limit=MAX_AUDIO_BYTES)
    if not audio:
        raise_error(400, "voice_bad_request", "音が空です")
    return {"text": await transcribe(session_id, audio, audio_type)}


@router.post("/sessions/{session_id}/voice/interruption")
async def post_interruption(request: Request, session_id: str) -> dict:
    """話している途中の人の言葉が取れた: そのタブの turn の実行中なら、 話し終えるのを待たずに止める。

    止め方は声の発話と同じ (= Escape。 入力欄は消さず、 停止の印も付けない)。 話し終えた発話は普段の送信口で送る。
    header: X-Voice-Conversation (省略可) = 会話を開いた画面の名前。 持ち主でない画面からは断る
    """
    _listening(session_id)
    client = request.headers.get(CONVERSATION_HEADER, "")
    if client and _conversations.setdefault(session_id, client) != client:
        raise_error(409, "voice_conversation_elsewhere", "このタブの会話は、 別の画面で開かれています")
    from backend.terminal.routes import interrupt_for_voice
    return {"stopped": await interrupt_for_voice(session_id)}


async def transcribe(session_id: str, audio: bytes, audio_type: str) -> str:
    """録った音を聞き取って、 その文を返す (= 画面の口と、 電話の会話が使う。 声が聞き取れなければ空の文)。"""
    listen = _listening(session_id)
    fields = {"response_format": "json", **({"prompt": listen["prompt"]} if listen["prompt"] else {})}
    started = time.monotonic()
    try:
        status, _, raw = await asyncio.to_thread(
            _call_listener, f"{listen['engine']}/inference", fields, audio, audio_type, LISTEN_TIMEOUT_SEC)
    except (OSError, http.client.HTTPException) as error:
        logger.warning("voice: listening engine could not be reached: %r", error)
        raise_error(502, "voice_listen_unreachable", "聞き取りの engine に繋がりません")
    try:
        heard = json.loads(raw) if status == 200 else None
    except ValueError:
        heard = None
    if not isinstance(heard, dict) or not isinstance(heard.get("text"), str):
        logger.warning("voice: listening engine failed status=%s", status)
        raise_error(502, "voice_listen_failed", f"聞き取りの engine が失敗しました ({status})", status=status)
    # engine は区切りごとに改行を挟む。 送る文は 1 行にまとめる (= 入力欄で改行が確定と読まれないように)。
    text = " ".join(line.strip() for line in heard["text"].splitlines() if line.strip())
    logger.info("voice: heard session=%s bytes=%d chars=%d ms=%d", session_id, len(audio), len(text),
                (time.monotonic() - started) * 1000)
    return text


@router.get("/sessions/{session_id}/voice/turn-model")
async def get_turn_model(session_id: str) -> FileResponse:
    """言い終えたかを判定する Smart Turn の model の file (= 画面が受け取って、 画面の中で判定する)。"""
    turn = _listening(session_id)["turn"]
    path = Path(turn).expanduser() if turn else None
    if path is None or not path.is_file():
        if turn:
            logger.warning("voice: the turn model file is not there: %s", turn)
        raise_error(404, "voice_turn_model_missing", "言い終えを判定する model がありません")
    # 中身が変わった時だけ取り直させる (= 毎回 ETag で確かめる。 file は数 MB)。
    return FileResponse(path, media_type="application/octet-stream", headers={"Cache-Control": "no-cache"})


@router.post("/sessions/{session_id}/voice/conversation")
async def open_conversation(request: Request, session_id: str) -> dict:
    """この画面で会話を開く (= 前に開いていた画面からは、 次に音を送った時に断る)。

    body:
        client (str): 画面が名乗る名前 (= 画面を読み込むたびに作る)
    """
    _listening(session_id)
    client = await _client_of(request)
    _conversations[session_id] = client
    logger.info("voice: conversation opened session=%s", session_id)
    return {"client": client}


@router.delete("/sessions/{session_id}/voice/conversation")
async def close_conversation(request: Request, session_id: str) -> dict:
    """会話を閉じる (= 持ち主の画面からだけ。 別の画面が持っていれば、 そのまま)。

    body:
        client (str): 会話を開いた時に名乗った名前
    """
    _listening(session_id)
    client = await _client_of(request)
    closed = _conversations.get(session_id) == client
    if closed:
        del _conversations[session_id]
    return {"closed": closed}


# --- 電話の会話 (= backend/voice_call/) が使う口 ------------------------------------------------------------------

def conversation_settings(session_id: str) -> dict:
    """会話に使う、 そのタブの声の設定 (= 持ち主は動かさない)。 声を持たない / 聞き取らないタブは、 画面の口と
    同じ error を投げる。"""
    _listening(session_id)
    return _enabled(session_id)
