"""Cut the answer of a turn out of the screen of a Claude Code pane, so far as it is drawn. A pure function: nothing here
touches tmux (= `screen_watch.py` reads the screen and calls in here).

Claude Code writes an answer a screen line at a time while the turn runs, but not into its record before the block is
done. What the screen shows is the answer as Claude Code draws it: after Markdown (= the lines of a code fence are
not there) and cut into lines of the pane's width, so it is not the answer character for character. It is for showing
the answer early; the exact answer is the `Stop` hook's.

The shape of the screen (measured in a real tab, `docs/reference/ask.md`):

    ❯ <the question as typed>
    ⏺ <first line of the answer>
      <the next line, indented by two>
                                              (a blank line between paragraphs)
    ✻ Doing… (3s · ↓ 60 tokens)               (the spinner, while the turn runs; `✻ Brewed for 6s · done` after it)
      ⎿  Tip: …
    ──────────────────────
    ❯ <the input box>
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Mapping

ANSWER_MARK = "⏺"
QUESTION_MARK = "❯ "
NOTE_MARK = "⎿"
INDENT = "  "
#: How many characters of the question's first line tell its echo from the other lines of the screen
QUESTION_KEY_CHARS = 10
#: A line this close to the pane's width (or wider) is a line Claude Code cut, not one that ended there: the width
#: left over is one column at most, a wide character not fitting, and the margin covers a few columns more.
WRAP_MARGIN_COLUMNS = 4
_WIDE_KINDS = "WF"
#: The echo of a question Claude Code folded into a placeholder (= a long or many-line text it was pasted as)
_PASTED_ECHO = re.compile(r"\[Pasted text #(\d+)")


def display_width(text: str) -> int:
    """The columns `text` takes in a terminal: two for a wide (= full-width) character, one for any other."""
    return sum(2 if unicodedata.east_asian_width(char) in _WIDE_KINDS else 1 for char in text)


def pasted_counts(screen: str) -> Counter[str]:
    """How many echoes of each pasted-text placeholder (= `❯ [Pasted text #N …]`, by its number) `screen` shows."""
    counts: Counter[str] = Counter()
    for line in screen.splitlines():
        if line.startswith(QUESTION_MARK):
            counts.update(_PASTED_ECHO.findall(line))
    return counts


def answer_from_screen(screen: str, question: str, pane_width: int,
                       pasted_before: Mapping[str, int] | None = None) -> str | None:
    """The answer to `question` as far as `screen` shows it, with the lines Claude Code cut joined again.

    `screen` is the pane with its scrollback (= `capture-pane -p -J -S -`), `pane_width` its columns. The answer starts
    at the first `⏺` line after the last line that echoes the question: its first line, or, for a question Claude Code
    folded into a `[Pasted text #N …]` placeholder, the last placeholder echo that the screen read right before the
    typing (`pasted_counts`, given as `pasted_before`) had fewer of. It ends before the spinner, a
    `⎿` note or the rule under it. A line of the pane's width (minus `WRAP_MARGIN_COLUMNS`) continues in the next one;
    any other line ends a line of the answer, and a blank line a paragraph (= `\\n\\n`). The fence of a ```json block
    is not on the screen, so it is not in the text either.
    → None when the question's echo is not on the screen, or no answer line follows it yet; "" when the answer has
    begun and has no text yet."""
    key = _question_key(question)
    if not key:
        return None
    lines = screen.splitlines()
    echoes = [index for index, line in enumerate(lines) if _echoes(line, key)]
    if pasted_before is not None:
        echoes += _new_pasted_echoes(lines, pasted_before)
    if not echoes:
        return None
    start = _answer_start(lines, max(echoes))
    if start is None:
        return None
    return _join_lines(_answer_lines(lines, start), pane_width)


def _question_key(question: str) -> str:
    """The first characters of the question's first line, without spaces (= Claude Code may draw a typed space again)."""
    for line in question.splitlines():
        if line.strip():
            return "".join(line.split())[:QUESTION_KEY_CHARS]
    return ""


def _echoes(line: str, key: str) -> bool:
    return line.startswith(QUESTION_MARK) and "".join(line[len(QUESTION_MARK):].split()).startswith(key)


def _new_pasted_echoes(lines: list[str], pasted_before: Mapping[str, int]) -> list[int]:
    """The index of the last placeholder echo whose number shows more often than before the typing (= the new one is the
    question's; an echo of an earlier ask was there already). Empty when there is none: no new placeholder, or old ones
    scrolled off the read lines meanwhile, when nothing is taken rather than an earlier answer."""
    counts = pasted_counts("\n".join(lines))
    for index in range(len(lines) - 1, -1, -1):
        if not lines[index].startswith(QUESTION_MARK):
            continue
        numbers = _PASTED_ECHO.findall(lines[index])
        if numbers:
            return [index] if counts[numbers[-1]] > pasted_before.get(numbers[-1], 0) else []
    return []


def _answer_start(lines: list[str], echo: int) -> int | None:
    """The index of the first answer line after the question's echo; None when another prompt comes first."""
    for index in range(echo + 1, len(lines)):
        if lines[index].startswith(ANSWER_MARK):
            return index
        if lines[index].startswith(QUESTION_MARK):
            return None
    return None


def _answer_lines(lines: list[str], start: int) -> list[str | None]:
    """The lines of the answer without their indent (= None for a blank one), up to its end."""
    found: list[str | None] = [lines[start][len(ANSWER_MARK) + 1:]]
    for line in lines[start + 1:]:
        if not line.strip():
            found.append(None)
        elif line.startswith(INDENT) and not line.lstrip().startswith(NOTE_MARK):
            found.append(line[len(INDENT):])
        else:
            break
    return found


def _join_lines(answer_lines: list[str | None], pane_width: int) -> str:
    text = ""
    is_paragraph_break = False
    is_cut = False
    for line in answer_lines:
        if line is None:
            is_paragraph_break = True
            continue
        line = line.rstrip()
        if not text:
            text = line
        elif is_paragraph_break:
            text += "\n\n" + line
        elif is_cut:
            text += _join_mark(text[-1], line[:1]) + line
        else:
            text += "\n" + line
        is_paragraph_break = False
        is_cut = display_width(INDENT + line) >= pane_width - WRAP_MARGIN_COLUMNS
    return text


def _join_mark(before: str, after: str) -> str:
    """What fills the cut between two lines: nothing between wide characters (= no spaces in the text), a space else."""
    if not after or display_width(before) == 2 or display_width(after) == 2:
        return ""
    return " "
