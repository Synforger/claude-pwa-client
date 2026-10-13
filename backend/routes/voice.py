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
      "default": "calm"
    }

    engine:  VOICEVOX と同じ口 (= `POST /audio_query` と `POST /synthesis`) を持つ engine の URL
    speaker: 声の番号 (= engine が `GET /speakers` で出す style の id)
    query:   どの文にも当てる値 (= engine が問い合わせに返す値のうち、 同じ名前の物を上書きする)
    marks:   言い方の印。 名前 → その印の文に当てる値。 `speaker` を書いた印は、 その文だけ別の声の番号で言う
    default: 印の無い文の印 (= 省けば最初の印)

流れは 2 段。 画面は返事の文を `utterances` へ渡して声にする文の並びを受け取り、 1 文ずつ `synthesis` へ
渡して音を受け取る (= 1 文目の音が出来た時点で鳴らし始められる。 engine は文の途中の音を返さない)。

    1. POST /sessions/{sid}/voice/utterances   返事の文 → 声にする文と、 その印
    2. POST /sessions/{sid}/voice/synthesis    1 文と印 → 音 (= audio/wav)

何を声にするか (= コードや path を飛ばし、 文に切り、 印を剥がす) は `backend/core/speech.py` が持つ。
ここが持つのは、 どのタブが声を持つか・engine へ渡す値・失敗の返し方。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, Request
from fastapi.responses import Response

import backend.config as _config
from backend.core.speech import MARK_NAME, speakable, utterances
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


def voice_settings(raw) -> dict | None:
    """agent の設定の `voice` を、 使える形にして返す。 形の違う設定は「声なし」 (= None)。"""
    if not isinstance(raw, dict):
        return None
    engine, speaker = raw.get("engine"), raw.get("speaker")
    if not isinstance(engine, str) or not engine.startswith(("http://", "https://")) or not _is_speaker(speaker):
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
    return {"engine": engine.rstrip("/"), "speaker": speaker, "query": query,
            "marks": {name: dict(value) for name, value in marks.items()}, "default": default}


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
    return settings


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


def _call_engine(url: str, body: dict | None, timeout: float) -> tuple[int, str, bytes]:
    """engine を 1 回呼んで (HTTP の状態, 返った物の種類, 中身) を返す。 繋がらなければ OSError。"""
    data = json.dumps(body).encode("utf-8") if body is not None else b""
    request = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (= url は設定の物)
            return response.status, response.headers.get_content_type(), response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get_content_type(), error.read()


async def _engine(step: str, url: str, body: dict | None) -> tuple[str, bytes]:
    """engine の 1 段を呼ぶ。 繋がらない・断られた時は、 どの段かを付けて 502 にする。"""
    try:
        status, kind, raw = await asyncio.to_thread(_call_engine, url, body, ENGINE_TIMEOUT_SEC)
    except OSError as error:
        logger.warning("voice: engine could not be reached step=%s: %s", step, error)
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
    """そのタブが声を持つかと、 言い方の印の一覧。"""
    settings = _settings_of(session_id)
    if settings is None:
        return {"enabled": False, "marks": [], "default": ""}
    return {"enabled": True, "marks": list(settings["marks"]), "default": settings["default"]}


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
    said = utterances(text, settings["marks"], settings["default"])
    return {"utterances": [{"mark": u.mark, "text": u.text} for u in said]}


@router.post("/sessions/{session_id}/voice/synthesis")
async def post_synthesis(request: Request, session_id: str) -> Response:
    """1 文を、 印の言い方で音にして返す。

    body:
        text (str): 声にする 1 文 (= `utterances` が返した文)
        mark (str, 省略可): 言い方の印 (= 省けば既定の印)
    """
    settings = _enabled(session_id)
    text, body = await _text_of(request)
    name = body.get("mark", settings["default"])
    if not isinstance(name, str):
        raise_error(400, "voice_bad_request", "mark は文字列で渡します")
    if name and name not in settings["marks"]:
        raise_error(400, "voice_unknown_mark", f"この agent に無い印です: {name}", mark=name)
    text = text.strip()
    if not speakable(text):
        raise_error(400, "voice_nothing_to_say", "声にする文字がありません")
    if len(text) > MAX_UTTERANCE_CHARS:
        raise_error(413, "voice_text_too_long", f"文が長すぎます (上限 {MAX_UTTERANCE_CHARS} 文字)",
                    limit=MAX_UTTERANCE_CHARS)

    values = dict(settings["marks"].get(name, {}))
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
    kind, sound = await _engine("synthesis", f"{settings['engine']}/synthesis?speaker={speaker}", query)
    if not kind.startswith("audio/"):
        _engine_failed("synthesis", 200)
    logger.info("voice: session=%s mark=%s chars=%d bytes=%d ms=%d", session_id, name or "-", len(text),
                len(sound), (time.monotonic() - started) * 1000)
    return Response(content=sound, media_type=kind, headers={"Cache-Control": "no-store"})
