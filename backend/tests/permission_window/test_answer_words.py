"""The words of a person that answer a window (`permission_window/answer_words.py`)."""
from __future__ import annotations

import pytest

from backend.permission_window import answer_words as words


@pytest.mark.parametrize("text, answer", [
    ("許可", words.ALLOW), ("  許可。 ", words.ALLOW), ("許可!", words.ALLOW),
    ("いいえ", words.DENY), ("だめ", words.DENY), ("拒否", words.DENY), ("だめ、", words.DENY),
])
def test_the_whole_utterance_is_an_answer(text, answer):
    assert words.answer_of(text) == answer


@pytest.mark.parametrize("text", ["はい", "許可します", "それは許可", "だめだと思う", "", "yes", "許可 拒否"])
def test_anything_else_is_not_an_answer(text):
    assert words.answer_of(text) is None


@pytest.mark.parametrize("text, answer", [("[voice] 許可", words.ALLOW), ("[voice] いいえ。", words.DENY)])
def test_the_mark_a_voice_puts_at_the_head_is_left_out_before_the_judgement(text, answer):
    assert words.answer_of(text) == answer


def test_a_voice_mark_alone_or_before_other_words_is_not_an_answer():
    assert words.answer_of("[voice]") is None and words.answer_of("[voice] 許可します") is None


def test_the_key_is_read_from_the_labels_not_assumed():
    choices = (("1", "No"), ("2", "Yes"))
    assert words.key_for(choices, words.ALLOW) == "2"
    assert words.key_for(choices, words.DENY) == "1"


def test_a_missing_line_has_no_key():
    assert words.key_for((("1", "Yes"),), words.DENY) is None
