"""agent の返事の文から、 声にする文を取り出す (= 文字列だけを見る純粋関数)。

返事は markdown で書かれていて、 人が声で聞いて意味を成すのは文の部分だけ。 コードブロック・表・
インラインのコード・path・URL は読まずに飛ばし、 見出しや箇条書きの記号と強調の記号は剥がす。 残った
文を句点・感嘆符・疑問符と改行で切り、 1 文ずつ返す。

文頭の `[名前]` は「この文をどう言うか」 の印 (= 名前は呼び手が渡す一覧の物だけ)。 印は文から剥がし、
その行の終わりまで効く (= 行の中で別の印が出れば、 そこから切り替わる)。 印の無い行は既定の印。
一覧に無い `[…]` と、 文の途中の `[…]` は、 ただの文として残る。

予約の印 `[mute]` (= MUTE_MARK) の行は声にしない (= 吹き出しには出る。 声で言う事と目で見せる事を 1 つの返事の
中で分ける)。 効く範囲は他の印と同じく行の終わりまでで、 行の中で別の印が出れば、 そこから声に戻る。 設定の marks
に同じ名前が在っても、 予約の印として扱う。

行の頭 (= 記号と印を剥がした後) が `Sources:` か `出典:` の行から返事の終わりまでは、 出典の塊として声にしない
(= 調べた後に付く題と URL の並び。 吹き出しには出る)。 コードブロックの中の同じ行は、 ここに当たらない。

印には、 その文だけの値を添えられる (= `[happy i=1.2 s=1.1]`)。 添えた値は印の値の上に重なり、 印と同じく
行の終わりまで効く。 添えられるのは VALUES の名前 (= 短い別名でも、 engine の名前でも) で、 範囲は
VALUE_RANGES。 名前の違う値と範囲の外の値は、 その文では使わない (= 印の値で言う)。

core/ に置く理由: 何を声にするかは、 音を作る側 (= routes) と切り離して test できる底の決まり。
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import NamedTuple


class Utterance(NamedTuple):
    """声にする 1 文と、 その言い方の印と、 印に添えた値 (= engine の名前 → 数。 添えていなければ空)。"""
    mark: str
    text: str
    values: dict[str, float] = {}


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
# 声で聞いている印 (= そのタブの会話が開いている間に人が送った文の頭に付く。 画面の `features/voice/inputMark.js`
# と同じ印)。 返事の印とは逆向きで、 agent へ「この返事は声で聞かれる」 と伝える。 送信口はこの印で声の発話を見分ける。
VOICE_INPUT_MARK = "[voice]"
# 声で聞いている印を付けない文の頭 (= claude の入力欄が頭の 1 文字で特別に扱う command / shell / memory。 頭に印が
# 入ると、 普通の発話として読まれる)
_UNMARKED_HEAD = ("/", "!", "#")


# 会話が開いているのに印の無い turn (= 別のタブからの連絡・自動の入れ替え・裏の作業の知らせ) で、 hook が agent へ渡す
# 1 行 (= `routes/hooks.py`)。 agent からは 🔊 も 🎙 も見えないので、 印と同じ事をこの行で伝える。
VOICE_OPEN_CONTEXT = (
    "[voice-open] This turn was not typed or said by the person, but a conversation of this tab is open "
    "(the speaker or the microphone is on in a screen, or the app call is connected): the reply will be heard, "
    "so write it as for a turn marked [voice]."
)


def mark_voice_input(text: str) -> str:
    """そのタブへ送る文に、 声で聞いている印を付ける (= 空の文・特別な頭の文・印の付いた文はそのまま)。"""
    if not text.strip() or text.startswith(_UNMARKED_HEAD) or text.startswith(VOICE_INPUT_MARK):
        return text
    return f"{VOICE_INPUT_MARK} {text}"
# 印の名前の形 (= 設定に書く名前も、 文頭の `[名前]` も、 この形だけを印として認める)。
MARK_NAME = r"[A-Za-z]+"
# 予約の印: この印の行は声にしない (= 設定の marks には書かない。 書いても予約が勝つ)。
MUTE_MARK = "mute"
# 印に添えられる値: 短い別名 → engine の問い合わせの値の名前。
VALUES = {
    "i": "intonationScale",
    "s": "speedScale",
    "t": "tempoDynamicsScale",
    "p": "pitchScale",
    "v": "volumeScale",
}
# 値の範囲 (= 両端を含む)。 AivisSpeech Engine 1.2.0 が `/openapi.json` の AudioQuery の説明に書く範囲。
VALUE_RANGES = {
    "intonationScale": (0.0, 2.0),
    "speedScale": (0.5, 2.0),
    "tempoDynamicsScale": (0.0, 2.0),
    "pitchScale": (-0.15, 0.15),
    "volumeScale": (0.0, 2.0),
}
_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
_PAIR = re.compile(rf"([A-Za-z]+)=({_NUMBER})")
_MARK = re.compile(rf"^\s*\[({MARK_NAME})((?:\s+[A-Za-z]+={_NUMBER})*)\s*\]\s*")
# 出典の塊の頭の行 (= 記号を剥がした行の頭。 印が付いていても当たる)
_SOURCES = re.compile(rf"^(?:\[{MARK_NAME}[^\]]*\]\s*)?(?:Sources|出典)\s*[:：]")


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


def mark_values(pairs) -> tuple[dict[str, float], list[str]]:
    """印に添えた値 (= `i=1.2 s=1.1` の文字列か、 名前 → 数の組) を、 engine の名前 → 数にする。

    名前は短い別名でも engine の名前でもよい。 返すのは (使う値, 使わなかった物の説明の並び)。 名前の違う物と、
    数でない物と、 範囲の外の物は使わない。
    """
    items = [(m[1], m[2]) for m in _PAIR.finditer(pairs)] if isinstance(pairs, str) else list((pairs or {}).items())
    used: dict[str, float] = {}
    dropped: list[str] = []
    for name, raw in items:
        key = VALUES.get(name, name)
        try:
            value = float(raw) if not isinstance(raw, bool) else None
        except (TypeError, ValueError):
            value = None
        if key not in VALUE_RANGES or value is None:
            dropped.append(f"{name}={raw}")
            continue
        low, high = VALUE_RANGES[key]
        if not low <= value <= high:
            dropped.append(f"{name}={raw} (= {key} は {low}〜{high})")
            continue
        used[key] = value
    return used, dropped


def parse_mark(sentence: str, marks: Iterable[str]) -> tuple[str, dict[str, float], list[str], str] | None:
    """文頭の印 (= 値を添えた形も) を読む。 印でなければ None。 返すのは (名前, 値, 使わなかった値, 残りの文)。"""
    head = _MARK.match(sentence)
    if not head or head.group(1) not in set(marks):
        return None
    values, dropped = mark_values(head.group(2))
    return head.group(1), values, dropped, sentence[head.end():]


def utterances(text: str, marks: Iterable[str], default: str, dropped: list[str] | None = None) -> list[Utterance]:
    """返事の文を、 声にする文の並びにする。 marks は印として認める名前、 default は印の無い行の印。

    dropped を渡すと、 印に添えたのに使わなかった値の説明を足す (= 呼び手が log に出す)。
    """
    known = set(marks) | {MUTE_MARK}
    out: list[Utterance] = []
    fenced = False
    for raw in text.splitlines():
        if _FENCE.match(raw):
            fenced = not fenced
            continue
        if fenced or _TABLE.match(raw) or _RULE.match(raw):
            continue
        line = _plain(raw)
        if _SOURCES.match(line):
            break
        mark, values = default, {}
        for found in _SENTENCE.finditer(line):
            sentence = found.group(0)
            head = parse_mark(sentence, known)
            if head:
                mark, values, unused, sentence = head
                if dropped is not None:
                    dropped.extend(unused)
            sentence = sentence.strip()
            if sentence and speakable(sentence) and mark != MUTE_MARK:
                out.append(Utterance(mark, sentence, values))
    return out
