"""`backend/core/speech.py` (= agent の返事の文から、 声にする文を取り出す)。

声にするのは人が話す文だけ。 コード・表・path・URL は読まずに飛ばし、 文ごとに切り、 文頭の印
(= `[happy]` 等) を剥がして印の名前として返す。 ここは文字列だけを見る (= 音は作らない)。
"""
from __future__ import annotations

import pytest

from backend.core.speech import utterances

MARKS = ("calm", "happy", "soft", "firm")


def said(text: str, marks=MARKS, default="calm") -> list[tuple[str, str]]:
    return [(u.mark, u.text) for u in utterances(text, marks, default)]


# --- 文に切る -------------------------------------------------------------------

def test_a_reply_is_cut_into_sentences_at_japanese_stops():
    assert said("できたよ。確認してね！まだある？") == [
        ("calm", "できたよ。"), ("calm", "確認してね！"), ("calm", "まだある？")]


def test_a_line_break_ends_a_sentence_that_has_no_stop():
    assert said("一行目\n二行目。") == [("calm", "一行目"), ("calm", "二行目。")]


def test_closing_brackets_stay_with_the_sentence_they_close():
    assert said("「できた。」と言った。") == [("calm", "「できた。」"), ("calm", "と言った。")]


def test_a_dot_inside_a_number_does_not_cut():
    assert said("値は 1.15 にした。") == [("calm", "値は 1.15 にした。")]


def test_repeated_stops_stay_in_one_sentence():
    assert said("えっ！？本当…。") == [("calm", "えっ！？"), ("calm", "本当…。")]


# --- 読まない物 -----------------------------------------------------------------

def test_a_fenced_code_block_is_not_spoken():
    text = "こう打つ。\n```bash\ngit status\n```\n終わり。"
    assert said(text) == [("calm", "こう打つ。"), ("calm", "終わり。")]


def test_a_code_block_left_open_is_not_spoken_to_its_end():
    assert said("見て。\n```\nprint(1)\nprint(2)") == [("calm", "見て。")]


def test_a_table_is_not_spoken():
    text = "結果はこれ。\n| 名前 | 値 |\n|---|---|\n| a | 1 |\n以上。"
    assert said(text) == [("calm", "結果はこれ。"), ("calm", "以上。")]


def test_inline_code_is_left_out_of_the_sentence():
    assert said("設定の `rollover` を足した。") == [("calm", "設定の を足した。")]


@pytest.mark.parametrize("path", ["~/notes/a.md", "/usr/local/bin/tool", "backend/routes/voice.py", "./run.sh"])
def test_a_path_is_left_out_of_the_sentence(path):
    assert said(f"場所は {path} だよ。") == [("calm", "場所は だよ。")]


def test_a_url_is_left_out_of_the_sentence():
    assert said("詳しくは https://example.com/a?b=1 を見て。") == [("calm", "詳しくは を見て。")]


def test_a_markdown_link_is_spoken_by_its_text():
    assert said("[手順書](https://example.com/guide) を読んで。") == [("calm", "手順書 を読んで。")]


def test_markdown_decoration_is_not_spoken():
    text = "## 結果\n- **できた**よ。\n1. 次は _確認_ だね。\n> 引用の文。"
    assert said(text) == [("calm", "結果"), ("calm", "できたよ。"), ("calm", "次は 確認 だね。"), ("calm", "引用の文。")]


def test_a_slash_between_japanese_words_is_kept():
    assert said("入力/出力を見る。") == [("calm", "入力/出力を見る。")]


def test_emoji_are_not_spoken():
    assert said("やった🎉 できたよ✅。") == [("calm", "やった できたよ。")]


@pytest.mark.parametrize("text", ["", "   \n\n", "```\ncode\n```", "| a | b |", "`x`", "…。", "🎉", "---"])
def test_text_with_nothing_to_say_gives_no_utterance(text):
    assert said(text) == []


# --- 印 ------------------------------------------------------------------------

def test_a_mark_at_the_head_of_a_sentence_names_how_it_is_said():
    assert said("[happy] やった！") == [("happy", "やった！")]


def test_a_mark_holds_to_the_end_of_its_line():
    assert said("[happy] やった！できたよ！\n次はこれ。") == [
        ("happy", "やった！"), ("happy", "できたよ！"), ("calm", "次はこれ。")]


def test_a_mark_can_change_inside_a_line():
    assert said("[happy] やった！[soft] 少し休もうか…。") == [("happy", "やった！"), ("soft", "少し休もうか…。")]


def test_a_sentence_with_no_mark_takes_the_default():
    assert said("ふつうの文。", default="firm") == [("firm", "ふつうの文。")]


def test_a_bracket_that_is_no_mark_is_spoken_as_text():
    assert said("[voice] 聞こえる？") == [("calm", "[voice] 聞こえる？")]


def test_a_mark_in_the_middle_of_a_sentence_is_text():
    assert said("印は [happy] と書く。") == [("calm", "印は [happy] と書く。")]


def test_a_mark_with_nothing_after_it_gives_no_utterance():
    assert said("[happy]") == []


def test_marks_are_matched_as_written():
    assert said("[Happy] やった！") == [("calm", "[Happy] やった！")]
