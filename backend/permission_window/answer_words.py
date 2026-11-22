"""The words of a person that answer a permission window, and the key of the window's choice an answer types. Pure.

Used by `terminal/routes.py` (the person's send) and `window_answer.py`.
"""
from __future__ import annotations

from backend.speech.speech import VOICE_INPUT_MARK

ALLOW = "allow"
DENY = "deny"

# The whole utterance, with the voice mark, the spaces and the punctuation around it left out, that answers the window.
# "はい" is not one of them: it also answers a question the agent asked in the chat.
_ALLOW_WORDS = frozenset({"許可"})
_DENY_WORDS = frozenset({"いいえ", "だめ", "拒否"})
_AROUND = " \t\r\n　。、．，.,!！?？"

# The labels of the window's two choices.
ALLOW_LABEL = "Yes"
DENY_LABEL = "No"


def answer_of(text: str) -> str | None:
    """`ALLOW` or `DENY` when the whole of `text` is an answer word, else None. The mark a voice puts at the head of what
    it heard is left out first (= the judgement is made on what was said, not on the mark)."""
    word = text.removeprefix(VOICE_INPUT_MARK).strip(_AROUND)
    if word in _ALLOW_WORDS:
        return ALLOW
    if word in _DENY_WORDS:
        return DENY
    return None


def key_for(choices: tuple[tuple[str, str], ...], answer: str) -> str | None:
    """The key to type for `answer` among the window's `choices` (`(key, label)`): the line labelled `Yes` for an allow, the
    line labelled `No` for a deny. None when the line is not there."""
    wanted = ALLOW_LABEL if answer == ALLOW else DENY_LABEL
    for key, label in choices:
        if label == wanted:
            return key
    return None
