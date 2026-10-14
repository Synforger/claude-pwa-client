"""電話の会話の決まり (= Pipecat に依らない、 文字と event だけを見る純粋関数)。

画面の会話と同じ決まりを、 backend の中の会話でも使う:
    声で聞いている印     `frontend/src/features/voice/inputMark.js`
    言いさし             `frontend/src/features/voice/turnTaker.js` の isUnfinished
    声にする返事         `frontend/src/features/voice/listener.js` の speechParts
"""
from __future__ import annotations

import re

from backend.core.jsonl_predicates import is_harness_xml_text
from backend.core.speech import VOICE_INPUT_MARK, parse_mark

# 声で聞いている印を付けない文の頭 (= 印そのものは core/speech.py の VOICE_INPUT_MARK)
_SPECIAL_HEAD = ("/", "!", "#")

# 覚えておく「言った物」 の数 (= 超えた分は古い順に忘れる。 会話を始める前の物は時刻で弾かれる)
MAX_HEARD = 2000


def mark_voice_input(text: str) -> str:
    """そのタブへ送る文に、 声で聞いている印を付ける。"""
    if not text.strip() or text.startswith(_SPECIAL_HEAD) or text.startswith(VOICE_INPUT_MARK):
        return text
    return f"{VOICE_INPUT_MARK} {text}"


# iPhone の app の小窓 (= PiP) に出す文。 別のタブからの連絡と自動の入れ替えは、 封筒の頭で見分けて出さない
# (= 人の発話ではない)。 割り込んだ時に claude が書く中断の行も出さない。 返事の行の頭の言い方の印
# (= `[happy]` / `[mute]`) は外す
_ENVELOPE_HEADS = ("Message from ", "Automatic session rollover", "<")
_LINE_MARK = re.compile(r"^\[[a-z][^\]\n]*\]\s*", re.MULTILINE)

# 小窓は行の中の markdown (= 太字・斜体・コード) だけを描く (= app の `CallPicture.swift`)。 行単位の形は
# ここで小窓で読める行に直す: 表は区切りの行を外してセルを「｜」 でつなぎ (= 見出しの行は太字)、 見出しは太字、
# 箇条書きは「・」、 引用の印・コードの囲みの行・区切りの線は外す
_TABLE_ROW = re.compile(r"^\s*\|(.*)\|\s*$")
_TABLE_RULE = re.compile(r"^\s*\|?(\s*:?-{3,}:?\s*\|)+\s*(:?-{3,}:?\s*)?$")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+")
_QUOTE = re.compile(r"^\s*>\s?")
_FENCE = re.compile(r"^\s*(```|~~~)")
_RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")


def shown_user_text(text: str | None) -> str | None:
    """タブの人の発話を、 小窓に出す文にする (= 声で聞いている印は外す。 出さない物は None)。"""
    said = (text or "").strip()
    if said.startswith(VOICE_INPUT_MARK):
        said = said[len(VOICE_INPUT_MARK):].strip()
    if not said or said.startswith(_ENVELOPE_HEADS) or is_harness_xml_text(said):
        return None
    return said


def shown_reply_text(text: str | None) -> str:
    """タブの返事を、 小窓に出す文にする (= 声にしない `[mute]` の行も出す。 印を外し、 行単位の markdown を直す)。"""
    lines: list[str] = []
    in_table = False
    for line in _LINE_MARK.sub("", text or "").split("\n"):
        if _FENCE.match(line) or _TABLE_RULE.match(line):
            continue
        row = _TABLE_ROW.match(line)
        if row:
            cells = " ｜ ".join(cell.strip() for cell in row.group(1).split("|"))
            lines.append(cells if in_table else f"**{cells}**")
            in_table = True
            continue
        in_table = False
        if _RULE.match(line):
            continue
        heading = _HEADING.match(line)
        if heading:
            lines.append(f"**{heading.group(1)}**")
            continue
        lines.append(_BULLET.sub(r"\1・", _QUOTE.sub("", line)))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


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
