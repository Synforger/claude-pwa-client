"""電話の会話の決まり (= Pipecat に依らない、 文字と event だけを見る純粋関数)。

画面の会話と同じ決まりを、 backend の中の会話でも使う:
    声で聞いている印     `frontend/src/features/voice/inputMark.js`
    言いさし             `frontend/src/features/voice/turnTaker.js` の isUnfinished
    声にする返事         `frontend/src/features/voice/listener.js` の speechParts
"""
from __future__ import annotations

import re

from backend.core.speech import parse_mark

# 声で聞いている印 (= 画面の `features/voice/inputMark.js` と同じ印と、 付けない文の決まり)
VOICE_INPUT_MARK = "[voice]"
_SPECIAL_HEAD = ("/", "!", "#")

# 覚えておく「言った物」 の数 (= 超えた分は古い順に忘れる。 会話を始める前の物は時刻で弾かれる)
MAX_HEARD = 2000


def mark_voice_input(text: str) -> str:
    """そのタブへ送る文に、 声で聞いている印を付ける。"""
    if not text.strip() or text.startswith(_SPECIAL_HEAD) or text.startswith(VOICE_INPUT_MARK):
        return text
    return f"{VOICE_INPUT_MARK} {text}"


def is_unfinished(text: str, endings: list[str]) -> bool:
    """言いさしか (= 送らずに続きを待つ)。 文の終わりの句点・記号・空白は見ずに比べる。"""
    said = text.strip()
    if not said:
        return False
    bare = said.rstrip("。．.!！?？ \t\n")
    return any(said.endswith(e) or (bare and bare.endswith(e)) for e in endings)


def speech_of(event: dict) -> tuple[str, str] | None:
    """event から、 声にする返事の文と、 同じ物を 2 度言わないための名前を取り出す (= 無ければ None)。"""
    if event.get("type") != "assistant" or event.get("parent_tool_use_id"):
        return None
    content = (event.get("message") or {}).get("content")
    if not isinstance(content, list):
        return None
    text = "".join(b.get("text") or "" for b in content if isinstance(b, dict) and b.get("type") == "text")
    uuid = event.get("uuid")
    return (f"{uuid}:text", text) if text.strip() and uuid else None


# 声にする 1 文の頭に付ける言い方の印 (= `[calm]今日は…` / `[happy intonationScale=1.2]…`)。 返事の文に agent が
# 書く印と同じ書き方で、 読むのも同じ所 (= core/speech.py の parse_mark)。


def marked(mark: str, text: str, values: dict | None = None) -> str:
    """言い方の印 (= 添えた値も) を付けた 1 文 (= 合成の部品へ渡す形)。"""
    if not mark:
        return text
    added = "".join(f" {name}={value}" for name, value in (values or {}).items())
    return f"[{mark}{added}]{text}"


def split_mark(text: str, marks) -> tuple[str | None, dict, str]:
    """`marked` で付けた印を剥がす (= 一覧に無い印は、 ただの文として残す)。 返すのは (印 または None, 値, 文)。"""
    found = parse_mark(text, marks)
    if found:
        mark, values, _, rest = found
        return mark, values, rest
    return None, {}, text
