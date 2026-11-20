"""Read the screen of a tab an ask typed into, over and over, and hand each new state of the answer on. Used by
`ask_turn.py` for an ask that wants the answer while the turn runs (= `tabs ask --stream`).

The cutting is `screen_answer.py`; this file only reads the pane (= tmux) and notices that the answer changed.
"""
from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Callable
from typing import NamedTuple

from backend.ask.screen_answer import answer_from_screen, pasted_counts
from backend.terminal import runner

logger = logging.getLogger(__name__)

#: How often the screen is read: Claude Code draws a new line of the answer about every half to one second
POLL_SEC = 0.5
#: How many lines of scrollback are read with the screen. The answer starts above the visible lines once it is longer
#: than the pane; a whole history would be read every poll.
HISTORY_LINES = 400
READ_TIMEOUT_SEC = 2.0


class PaneScreen(NamedTuple):
    """What one read of a pane gives: its width in columns and its text (= scrollback and visible lines)."""
    width: int
    text: str


def read_screen(session_id: str) -> PaneScreen | None:
    """The pane of the tab with its scrollback, joined where the terminal wrapped a line. Blocking.
    → None when tmux does not answer or the pane is gone (= the next read tries again)."""
    target = runner._tmux_session_name(session_id)
    result = runner._run_tmux(
        "display-message", "-p", "-t", target, "#{pane_width}",
        ";",
        "capture-pane", "-p", "-J", "-S", f"-{HISTORY_LINES}", "-t", target,
        timeout=READ_TIMEOUT_SEC,
    )
    if result is None or result.returncode != 0:
        return None
    width_line, _, text = result.stdout.decode("utf-8", errors="replace").partition("\n")
    try:
        return PaneScreen(int(width_line), text)
    except ValueError:
        return None


def read_pasted_counts(session_id: str) -> Counter[str] | None:
    """The pasted-text placeholders the tab's screen shows now (`screen_answer.pasted_counts`), read right before an
    ask types, so that the echo of its own placeholder can be told from earlier ones. Blocking. → None when the screen
    could not be read (= a folded question then gets no partial answer)."""
    screen = read_screen(session_id)
    return pasted_counts(screen.text) if screen is not None else None


async def watch(session_id: str, question: str, emit: Callable[[str], None],
                pasted_before: Counter[str] | None = None) -> None:
    """Read the tab's screen every `POLL_SEC` and call `emit` with the answer to `question` each time it is different
    from the last one handed on. `pasted_before` is `read_pasted_counts` taken right before the typing. Runs until
    cancelled; a failed read or an answer not on the screen yet emits nothing."""
    last: str | None = None
    try:
        while True:
            screen = await asyncio.to_thread(read_screen, session_id)
            text = (answer_from_screen(screen.text, question, screen.width, pasted_before)
                    if screen is not None else None)
            if text and text != last:
                last = text
                emit(text)
            await asyncio.sleep(POLL_SEC)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("screen watch stopped: session=%s", session_id)
