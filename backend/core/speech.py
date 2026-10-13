"""agent の返事の文から、 声にする文を取り出す (= 文字列だけを見る純粋関数)。

返事は markdown で書かれていて、 人が声で聞いて意味を成すのは文の部分だけ。 コードブロック・表・
インラインのコード・path・URL は読まずに飛ばし、 見出しや箇条書きの記号と強調の記号は剥がす。 残った
文を句点・感嘆符・疑問符と改行で切り、 1 文ずつ返す。

文頭の `[名前]` は「この文をどう言うか」 の印 (= 名前は呼び手が渡す一覧の物だけ)。 印は文から剥がし、
その行の終わりまで効く (= 行の中で別の印が出れば、 そこから切り替わる)。 印の無い行は既定の印。
一覧に無い `[…]` と、 文の途中の `[…]` は、 ただの文として残る。

core/ に置く理由: 何を声にするかは、 音を作る側 (= routes) と切り離して test できる底の決まり。
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import NamedTuple


class Utterance(NamedTuple):
    """声にする 1 文と、 その言い方の印。"""
    mark: str
    text: str


_FENCE = re.compile(r"^\s*(```|~~~)")
# 表の行と、 区切りの線 (= `---` / `***` / `===`)。
_TABLE = re.compile(r"^\s*\|")
_RULE = re.compile(r"^\s*[-*=_\s]{3,}$")
# 行の頭の記号: 引用 / 見出し / 箇条書き / 番号。
_LEAD = re.compile(r"^\s*(?:>+\s*)*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)?")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_CODE = re.compile(r"`[^`]*`")
_URL = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+")
# path らしい並び (= 区切りの `/` を挟んだ英数字の語)。 日本語の語を挟む `/` (= 入力/出力) には当たらない。
_PATHISH = re.compile(r"(?<![A-Za-z0-9_])[~.A-Za-z0-9_\-]*(?:/[A-Za-z0-9_.\-]+)+/?")
_EMPHASIS_UNDERSCORE = re.compile(r"(?<![A-Za-z0-9])_(.+?)_(?![A-Za-z0-9])")
_EMPHASIS = re.compile(r"\*+|~~")
# 絵文字と、 それに付く結合の文字。
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")
_SPACES = re.compile(r"[ \t　]+")
# 文の終わり: 句点・感嘆符・疑問符の並びと、 それに続く閉じ括弧。
_SENTENCE = re.compile(r".*?[。！？!?]+[」』）)】]*|.+$")
# 印の名前の形 (= 設定に書く名前も、 文頭の `[名前]` も、 この形だけを印として認める)。
MARK_NAME = r"[A-Za-z]+"
_MARK = re.compile(rf"^\s*\[({MARK_NAME})\]\s*")


def _drop_path(match: re.Match[str]) -> str:
    token = match.group(0)
    # 数字だけの並び (= 10/14 や 1/2) は path ではない。
    return "" if re.search(r"[A-Za-z~]", token) or token.startswith("/") else token


def _plain(line: str) -> str:
    """1 行から、 声にしない物を落とし、 記号を剥がす。"""
    line = _LEAD.sub("", line, count=1)
    line = _IMAGE.sub("", line)
    line = _LINK.sub(r"\1", line)
    line = _CODE.sub("", line)
    line = _URL.sub("", line)
    line = _PATHISH.sub(_drop_path, line)
    line = _EMPHASIS_UNDERSCORE.sub(r"\1", line)
    line = _EMPHASIS.sub("", line)
    line = _EMOJI.sub("", line)
    return _SPACES.sub(" ", line).strip()


def speakable(text: str) -> bool:
    """読む文字 (= 文字か数字) が 1 つでも在るか。 記号だけの並びは声にしない。"""
    return any(ch.isalnum() for ch in text)


def utterances(text: str, marks: Iterable[str], default: str) -> list[Utterance]:
    """返事の文を、 声にする文の並びにする。 marks は印として認める名前、 default は印の無い行の印。"""
    known = set(marks)
    out: list[Utterance] = []
    fenced = False
    for raw in text.splitlines():
        if _FENCE.match(raw):
            fenced = not fenced
            continue
        if fenced or _TABLE.match(raw) or _RULE.match(raw):
            continue
        line = _plain(raw)
        mark = default
        for found in _SENTENCE.finditer(line):
            sentence = found.group(0)
            head = _MARK.match(sentence)
            if head and head.group(1) in known:
                mark = head.group(1)
                sentence = sentence[head.end():]
            sentence = sentence.strip()
            if sentence and speakable(sentence):
                out.append(Utterance(mark, sentence))
    return out
