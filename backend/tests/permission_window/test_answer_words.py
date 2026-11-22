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


def test_the_key_is_read_from_the_labels_not_assumed():
    choices = [{"key": "1", "label": "No"}, {"key": "2", "label": "Yes"}]
    assert words.key_for(choices, words.ALLOW) == "2"
    assert words.key_for(choices, words.DENY) == "1"


def test_a_missing_line_has_no_key():
    assert words.key_for([{"key": "1", "label": "Yes"}], words.DENY) is None
