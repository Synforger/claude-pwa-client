"""The answer cut out of the screen of a Claude Code pane (`backend/ask/screen_answer.py`).

The screens in `screens/` are real ones of a tab set up for asks (120 columns, scrollback included), read while a turn
ran; their text is a story made up for the test.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.ask.screen_answer import answer_from_screen, display_width

SCREENS = Path(__file__).parent / "screens"
WIDTH = 120
SHORT_QUESTION = "こんにちは。港町を舞台に、短い一場面を書いてください。"
LONG_QUESTION = (
    "霧の港町の夜明けを舞台に、物語の次の一場面を書いてください。形は次のとおりです。まず地の文を 6 文から 8 文で書き、"
    "その後ろに、```json の囲みで {\"narration\": \"<地の文を 2 文に縮めた物>\", \"choices\": [\"<選択肢 1>\", "
    "\"<選択肢 2>\", \"<選択肢 3>\"]} を書いてください。地の文は情景と人物の動きを細かく描き、前置きや後書きは付けないでください。\n"
)
PROSE_START = "霧は夜明けの港をすっぽりと包み、岸壁の端から先は白い壁のように何も見えなかった。"
PROSE_END = "ミナトの手の中では、昨夜拾った錆びた鍵が、じっとりと汗ばんで熱を帯びていた。"


def screen(name: str) -> str:
    return (SCREENS / f"{name}.txt").read_text(encoding="utf-8")


def test_a_turn_that_has_drawn_no_answer_yet_has_none():
    assert answer_from_screen(screen("thinking"), SHORT_QUESTION, WIDTH) is None


def test_the_answer_so_far_has_its_cut_lines_joined_and_its_last_line_cut_short():
    text = answer_from_screen(screen("prose_midway"), LONG_QUESTION, WIDTH)
    assert text is not None and text.startswith(PROSE_START)
    assert text.endswith("人影はゆっくりと振り返らないまま、「来る")      # the line Claude Code was drawing
    assert "\n" not in text and "冷たさを掌で確かめながら" in text      # six screen lines, one line of text


def test_the_json_shows_without_its_fence_after_a_blank_line_and_is_one_text_with_the_prose():
    begun = answer_from_screen(screen("json_started"), LONG_QUESTION, WIDTH)
    assert begun is not None and begun.endswith(PROSE_END + "\n\n" + '{"narration":')
    done = answer_from_screen(screen("finished"), LONG_QUESTION, WIDTH)
    assert done is not None and done.startswith(begun[:-len('{"narration":')])
    narration = json.loads(done[done.index('{"narration"'):])
    assert narration["narration"].startswith("霧に包まれた夜明けの桟橋で") and len(narration["choices"]) == 3


def test_paragraphs_stay_apart_and_a_line_that_ended_short_stays_a_line():
    text = answer_from_screen(screen("short_answer_midway"), SHORT_QUESTION, WIDTH)
    assert text is not None
    paragraphs = text.split("\n\n")
    assert paragraphs[:4] == ["こんにちは。港町の一場面です。", "---", "夜明けの桟橋", "午前四時、港はまだ眠っていた。"]
    assert paragraphs[4].endswith("湯気の立つ缶コーヒーを両手で包んでいた。")      # two screen lines, one paragraph
    assert "\n" not in paragraphs[4]
    assert paragraphs[-3] == "「眠れなくて」\n「若いのに」源さんは笑って、隣に箱を下ろした。「船、出るぞ。乗るか」"
    assert paragraphs[-1] == "「そうか」"


def test_the_answer_of_the_last_echo_of_the_question_is_the_one_taken():
    # the screen after a /resume and a /branch shows the conversation twice, and each question more than once
    assert answer_from_screen(screen("after_resume_and_branch"), "ここまでの会話を、 ひとことで言うと何ですか。",
                              WIDTH) == ("港町を舞台にした短い場面を、朝の桟橋、雨の魚市場、霧の夜明け（選択肢付き）と、"
                                         "雰囲気を変えながら書き重ねてきた会話です。")
    assert answer_from_screen(screen("after_resume_and_branch"), "少し前の会話で、 あなたが書いた場面の舞台はどこでしたか。",
                              WIDTH) == "霧に包まれた夜明けの港の桟橋です。"
    second = answer_from_screen(screen("after_resume_and_branch"), SHORT_QUESTION, WIDTH)
    assert second is not None and second.startswith("こんにちは。もう一つ、別の港町の場面を書きました。")
    assert second.endswith("こちらも、トーンや長さを変えて書き直せます。")      # its own end, not the answer after it


def test_a_question_whose_echo_has_scrolled_off_the_screen_has_no_answer():
    assert answer_from_screen(screen("scrolled_off"), SHORT_QUESTION, WIDTH) is None


@pytest.mark.parametrize("question", ["", "\n  \n", "ほかの問い、 画面には無い"])
def test_a_question_that_is_not_on_the_screen_has_no_answer(question):
    assert answer_from_screen(screen("finished"), question, WIDTH) is None


def test_a_space_the_screen_draws_differently_does_not_hide_the_echo():
    assert answer_from_screen(screen("after_resume_and_branch"), "ここまでの会話を、ひとことで言うと何ですか。", WIDTH)


def test_the_width_decides_what_is_a_cut_line():
    lines = ["❯ Describe the tavern.", "", "⏺ The tavern is old and the roof of it leans", "  to the left."]
    assert answer_from_screen("\n".join(lines), "Describe the tavern.", 46) == \
        "The tavern is old and the roof of it leans to the left."
    assert answer_from_screen("\n".join(lines), "Describe the tavern.", 120) == \
        "The tavern is old and the roof of it leans\nto the left."


def test_an_answer_that_has_begun_without_text_is_empty():
    assert answer_from_screen("❯ hello\n\n⏺\n✻ Doing…", "hello", WIDTH) == ""


def test_a_note_and_the_spinner_end_the_answer():
    lines = ["❯ hello", "", "⏺ Hi.", "", "  And a second line.", "✻ Doing… (2s · ↓ 12 tokens)", "  ⎿  Tip: a hint", "──"]
    assert answer_from_screen("\n".join(lines), "hello", WIDTH) == "Hi.\n\nAnd a second line."
    lines[5:7] = ["  ⎿  Tip: a hint"]
    assert answer_from_screen("\n".join(lines), "hello", WIDTH) == "Hi.\n\nAnd a second line."


def test_a_question_asked_again_has_no_answer_until_its_own_answer_is_drawn():
    lines = ["❯ hello", "⏺ Hi.", "✻ Brewed for 1s · done", "❯ hello", "✻ Doing…"]
    assert answer_from_screen("\n".join(lines), "hello", WIDTH) is None


def test_the_width_of_a_wide_character_is_two():
    assert display_width("港a") == 3


def _folded(text: str, number: str = "1") -> str:
    """The screen as Claude Code draws it when it folds the long question into a pasted-text placeholder."""
    lines = text.splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith("❯ 霧の港町"))
    lines[index] = f"❯ [Pasted text #{number} +434 lines]"
    while index + 1 < len(lines) and lines[index + 1].startswith("  ") and not lines[index + 1].startswith("  ⎿"):
        del lines[index + 1]                                # the echo's own wrapped lines go with it
    return "\n".join(lines)


def test_a_question_folded_into_a_placeholder_is_found_by_the_new_placeholder():
    folded = _folded(screen("finished"))
    text = answer_from_screen(folded, LONG_QUESTION, WIDTH, pasted_before={})
    assert text is not None and text.startswith(PROSE_START)


def test_a_placeholder_number_seen_again_after_a_cleared_conversation_is_the_new_one():
    earlier = "❯ [Pasted text #1 +500 lines]\n⏺ 前の問いの答え。\n\n✻ Brewed for 9s · done\n"
    folded = earlier + _folded(screen("finished"))
    text = answer_from_screen(folded, LONG_QUESTION, WIDTH, pasted_before={"1": 1})
    assert text is not None and text.startswith(PROSE_START)


def test_an_earlier_placeholder_alone_gives_no_answer_rather_than_the_earlier_one():
    earlier = "❯ [Pasted text #1 +500 lines]\n⏺ 前の問いの答え。\n\n✻ Brewed for 9s · done\n❯ \n"
    assert answer_from_screen(earlier, LONG_QUESTION, WIDTH, pasted_before={"1": 1}) is None


def test_without_the_screen_read_before_the_typing_a_folded_question_gives_no_answer():
    assert answer_from_screen(_folded(screen("finished")), LONG_QUESTION, WIDTH) is None
