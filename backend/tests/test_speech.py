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


# --- 印に添えた値 -------------------------------------------------------------------

def valued(text: str, marks=MARKS, default="calm") -> list[tuple[str, dict, str]]:
    return [(u.mark, u.values, u.text) for u in utterances(text, marks, default)]


def test_a_mark_without_values_has_none():
    assert valued("[happy] やった！") == [("happy", {}, "やった！")]


def test_values_after_a_mark_are_named_the_way_the_engine_names_them():
    assert valued("[happy i=1.2 s=0.9 t=1.4 p=0.05 v=1.5] やった！") == [("happy", {
        "intonationScale": 1.2, "speedScale": 0.9, "tempoDynamicsScale": 1.4, "pitchScale": 0.05, "volumeScale": 1.5,
    }, "やった！")]


def test_a_value_may_be_written_by_the_engine_name():
    assert valued("[soft intonationScale=0.6] そうだね。") == [("soft", {"intonationScale": 0.6}, "そうだね。")]


def test_values_hold_to_the_end_of_their_line_with_their_mark():
    assert valued("[happy i=1.5] やった！できた！\n次はこれ。") == [
        ("happy", {"intonationScale": 1.5}, "やった！"), ("happy", {"intonationScale": 1.5}, "できた！"),
        ("calm", {}, "次はこれ。")]


def test_a_new_mark_in_the_line_drops_the_values_of_the_last():
    assert valued("[happy i=1.5] やった！[soft] 休もう。") == [
        ("happy", {"intonationScale": 1.5}, "やった！"), ("soft", {}, "休もう。")]


@pytest.mark.parametrize("pair", ["i=2.5", "s=0.4", "p=0.2", "v=-1", "x=1.0", "speed=1.2"])
def test_a_value_out_of_range_or_of_no_known_name_is_not_used(pair):
    dropped = []
    said_ = utterances(f"[happy i=1.1 {pair}] やった！", MARKS, "calm", dropped)
    assert [(u.mark, u.values, u.text) for u in said_] == [("happy", {"intonationScale": 1.1}, "やった！")]
    assert len(dropped) == 1 and dropped[0].startswith(pair)


def test_the_ends_of_a_range_are_in_it():
    assert valued("[happy s=0.5 p=-0.15] ゆっくり。")[0][1] == {"speedScale": 0.5, "pitchScale": -0.15}


def test_values_after_a_name_that_is_no_mark_are_text():
    assert valued("[voice i=1.2] 聞こえる？") == [("calm", {}, "[voice i=1.2] 聞こえる？")]


# --- 予約の印 [mute] -----------------------------------------------------------------------------------------

def test_a_mute_line_is_not_spoken():
    assert said("[mute] 下の表を見て。\nまとめると、 良さそう。") == [("calm", "まとめると、 良さそう。")]


def test_a_mute_mark_holds_to_the_end_of_its_line_and_another_mark_brings_the_voice_back():
    assert said("[mute] 長い引用。 続きの引用。[happy] ここは言う！") == [("happy", "ここは言う！")]


def test_mute_is_reserved_even_when_the_marks_name_it():
    assert said("[mute] 言わない。", marks=(*MARKS, "mute")) == []


def test_mute_in_the_middle_of_a_sentence_is_text():
    assert said("印は [mute] と書く。") == [("calm", "印は [mute] と書く。")]


# --- 出典の塊 -------------------------------------------------------------------

def test_the_sources_block_at_the_end_of_a_reply_is_not_spoken():
    text = ("明日は晴れるよ。\n\nSources:\n- [天気予報](https://example.com/a)\n"
            "- [週間予報](https://example.com/b)")
    assert said(text) == [("calm", "明日は晴れるよ。")]


@pytest.mark.parametrize("head", ["出典:", "出典：", "**Sources:**", "## Sources:", "[happy] Sources:"])
def test_a_sources_head_ends_what_is_spoken_whatever_its_decoration(head):
    assert said(f"調べた。\n{head}\n- [題](https://example.com)\nあとがき。") == [("calm", "調べた。")]


def test_a_sources_line_inside_a_code_block_does_not_end_what_is_spoken():
    assert said("こう書く。\n```\nSources:\n```\n終わり。") == [("calm", "こう書く。"), ("calm", "終わり。")]


def test_sources_in_the_middle_of_a_line_is_text():
    assert said("この話の出典: 気象庁。") == [("calm", "この話の出典: 気象庁。")]
