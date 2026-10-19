"""返事の地の文が、 設定した言語ではない (= 英語に流れた) かを判定する純粋関数。

Claude Code の設定 (= `<config dir>/settings.json` の `language`) が日本語の時、 長い作業の途中で
code や道具の出力が文脈の大半を占めると、 地の文が英語に流れることがある。 その文を画面と通知に
そのまま出さないための判定で、 今判定できるのは「日本語の設定で英語の地の文」 の 1 組だけ
(= 他の言語の設定では何も止めない)。

英語の判定は、 code・URL・引用の行 (= `>`)・鉤括弧と引用符の中を除いた残りに、 英字が MIN_LETTERS 以上、
平仮名が MIN_KANA 字未満、 英語の機能語 (= the / and / I'll …) が MIN_FUNCTION_WORDS 語以上の時。
日本語の文には助詞と活用の平仮名が入り、 英語の文には機能語が並ぶ。 なので、 引用した日本語の語や
漢字の名前だけが入った英文は止まり、 日本語の前置きで始まる頼まれた英文と、 平仮名の少ない日本語の
報告に英語の名前が並ぶ文は通る (= 2 台の会話の記録 5859 文で、 流れた英文 108 は平仮名 0〜3 字・
機能語 4 語以上、 通す側は平仮名 22 字以上か機能語 2 語以下)。

単体の script からも読めるよう、 標準 library だけで書く (= backend の他の module を import しない)。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

MIN_LETTERS = 80        # 英字がこれより少ない文は見ない (= 1 行の確認や path だけの文)
MIN_KANA = 10           # 平仮名がこれより少なく
MIN_FUNCTION_WORDS = 3  # 機能語がこれ以上並べば英語 (= 実測で英語の側は 4 語以上、 通す側は 2 語以下)
FUNCTION_WORDS = frozenset("""the a an and or but so to of in on for with from at by as is are was were be been it its
this that these those i i'll i'm i've we you he she they will would can could should have has had not no do does did now
then when which what there here if than once""".split())
JAPANESE = ("日本語", "japanese", "ja", "ja-jp")


def prose(text: str) -> str:
    """地の文だけを残す (= code の枠は閉じ忘れも、 引用の行、 鉤括弧と同じ行の引用符の中を外す)。"""
    body = re.sub(r"(```|~~~).*?(?:\1|\Z)", "", text, flags=re.S)
    body = re.sub(r"`[^`\n]*`|https?://\S+", "", body)
    body = re.sub(r"(?m)^[ \t]*>.*$", "", body)
    return re.sub(r"「[^」]*」|『[^』]*』|“[^”\n]*”|\"[^\"\n]*\"", "", body)


def english(text: str) -> bool:
    body = prose(text)
    if len(re.findall(r"[A-Za-z]", body)) < MIN_LETTERS or len(re.findall(r"[ぁ-ゖ]", body)) >= MIN_KANA:
        return False
    return sum(1 for word in re.findall(r"[A-Za-z']+", body) if word.lower() in FUNCTION_WORDS) >= MIN_FUNCTION_WORDS


def is_japanese(language: str | None) -> bool:
    return (language or "").strip().lower() in JAPANESE


def foreign_prose(text: str, language: str | None) -> bool:
    """設定した言語が日本語で、 text の地の文が英語なら True。"""
    return is_japanese(language) and english(text)


_cache: dict[Path, tuple[float, str]] = {}


def configured_language(config_dir: Path) -> str:
    """Claude Code の設定の `language` (= 無い・読めない時は空)。 file の更新時刻で覚え直す。"""
    path = config_dir / "settings.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return ""
    hit = _cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        language = str(json.loads(path.read_text(encoding="utf-8")).get("language") or "")
    except (OSError, ValueError, AttributeError):
        language = ""
    _cache[path] = (mtime, language)
    return language
