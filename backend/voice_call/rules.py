"""電話の会話の決まり (= Pipecat に依らない、 文字と event だけを見る純粋関数)。

画面の会話と同じ決まりを、 backend の中の会話でも使う:
    声で聞いている印を外す `frontend/src/features/voice/inputMark.js` の hideVoiceInputMark (= 付けるのは
                           `core/speech.py` の mark_voice_input)
    言いさし             `frontend/src/features/voice/turnTaker.js` の isUnfinished
    声にする返事         `frontend/src/features/voice/listener.js` の speechParts
"""
from __future__ import annotations

import re
import unicodedata

from backend.core.jsonl_predicates import is_harness_xml_text
from backend.core.speech import VOICE_INPUT_MARK, parse_mark

# 覚えておく「言った物」 の数 (= 超えた分は古い順に忘れる。 会話を始める前の物は時刻で弾かれる)
MAX_HEARD = 2000


# iPhone の app の小窓 (= PiP) に出す文。 別のタブからの連絡と自動の入れ替えは、 封筒の頭で見分けて出さない
# (= 人の発話ではない)。 割り込んだ時に claude が書く中断の行も出さない。 返事の行の頭の言い方の印
# (= `[happy]` / `[mute]`) は外す
_ENVELOPE_HEADS = ("Message from ", "Automatic session rollover", "<")
_LINE_MARK = re.compile(r"^\[[a-z][^\]\n]*\](?!\()\s*", re.MULTILINE)   # (= 行の頭のリンク `[文字](URL)` は残す)

# 小窓は返事を markdown のまま受け取り、 表・見出し・箇条書き・コードの枠まで描く (= app の `ChatMarkdown.swift`)


def shown_user_text(text: str | None) -> str | None:
    """タブの人の発話を、 小窓に出す文にする (= 声で聞いている印は外す。 出さない物は None)。"""
    said = (text or "").strip()
    if said.startswith(VOICE_INPUT_MARK):
        said = said[len(VOICE_INPUT_MARK):].strip()
    if not said or said.startswith(_ENVELOPE_HEADS) or is_harness_xml_text(said):
        return None
    return said


# 返事の中の画像 (= `![説明](出どころ)`) と、 コードの囲みの線
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_FENCE = re.compile(r"^\s*(```|~~~)")


def shown_reply_text(text: str | None) -> str:
    """タブの返事を、 小窓に出す文にする (= 声にしない `[mute]` の行も出す。 行の頭の言い方の印だけを外す)。

    画像は小窓に描かず「🖼 説明」 の 1 行にする (= 画面では画像として出る。 コードの囲みの中はそのまま)。
    """
    lines, fenced = [], False
    for line in _LINE_MARK.sub("", text or "").split("\n"):
        if _FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            line = _IMAGE.sub(lambda m: "🖼 " + (m.group(1).strip() or "画像"), line)
        lines.append(line)
    return "\n".join(lines).strip()


def is_unfinished(text: str, endings: list[str]) -> bool:
    """言いさしか (= 送らずに続きを待つ)。 文の終わりの句点・記号・空白は見ずに比べる。"""
    said = text.strip()
    if not said:
        return False
    bare = said.rstrip("。．.!！?？ \t\n")
    return any(said.endswith(e) or (bare and bare.endswith(e)) for e in endings)


# 聞き取った文と声にした文を比べる前に外す物 (= 空白・句読点・記号。 字の幅は NFKC でそろえ、 漢数字は算用数字に
# 寄せる: 聞き取りは「3つの」、 返事は「3 つの」 や「三つの」 と書く)
_NOT_COMPARED = re.compile(r"[\s\W_]+")
_KANJI_DIGITS = str.maketrans("〇一二三四五六七八九", "0123456789")


def _compared(text: str) -> str:
    return _NOT_COMPARED.sub("", unicodedata.normalize("NFKC", text).translate(_KANJI_DIGITS)).lower()


def is_own_voice(heard: str, spoken: list[str]) -> bool:
    """聞き取った文が、 その時に声にしていた文の一部か (= スピーカーの声がマイクに入って、 人の発話として届いた)。

    spoken: 割り込みで止められた時に鳴っていた文と、 その前の文 (= 言い方の印は外した物)。 文の境目を跨いで
    聞こえた分も拾うよう、 つなげて比べる。
    """
    said = _compared(heard)
    return bool(said) and said in _compared("".join(spoken))


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
