"""Answers the window the pane shows: reads its choices from the screen and types one key.

The number of the choice is not assumed: the line labelled `Yes` is the allow and the line labelled `No` the deny
(`answer_words.key_for`), read from the pane just before the key is typed. A deny with no `No` line is an Escape. Nothing
is typed when the pane shows no choices (= the window is not on the screen), and the window is closed once the key is
typed, without waiting for the record.

Used by `routes/permission_window.py` and `terminal/routes.py` (an answer word of the person).
"""
from __future__ import annotations

import asyncio
import logging

from backend.permission_window import window_state
from backend.permission_window.answer_words import ALLOW, key_for
from backend.permission_window.window_state import Window
from backend.terminal.ansi_text import strip_ansi
from backend.terminal.pane_choices import choices_in_pane
from backend.terminal.prompt_detector_loop import note_user_input, poke_now
from backend.terminal.runner import capture_pane_ansi_tail, tmux_send_keys

logger = logging.getLogger(__name__)

CLOSED = {"ok": False, "reason": "closed"}


def _read_choices(session_id: str) -> list[dict]:
    return choices_in_pane(strip_ansi(capture_pane_ansi_tail(session_id) or ""), selection_marker=True)


def _type(session_id: str, key: str | None) -> bool:
    return tmux_send_keys(session_id, key="Escape") if key is None else tmux_send_keys(session_id, text=key)


async def answer(session_id: str, window: Window, answer_kind: str) -> dict:
    """Type the answer (`ALLOW` or `DENY` of `answer_words`) for `window`, the oldest permission window of the tab.
    → `{"ok": True}`; `{"ok": False, "reason": "closed"}` when the pane shows no choices; `{"ok": False, "reason":
    "no_yes_line"}` when an allow finds no `Yes` line; `{"ok": False, "reason": "not_typed"}` when tmux took no key."""
    choices = await asyncio.to_thread(_read_choices, session_id)
    if not choices:
        logger.info("permission window: not answered, the pane shows no choices session=%s number=%d", session_id,
                    window.number)
        return dict(CLOSED)
    key = key_for(choices, answer_kind)
    if key is None and answer_kind == ALLOW:
        logger.warning("permission window: no Yes line on the pane session=%s number=%d", session_id, window.number)
        return {"ok": False, "reason": "no_yes_line"}
    if not await asyncio.to_thread(_type, session_id, key):
        return {"ok": False, "reason": "not_typed"}
    logger.info("permission window: answered session=%s number=%d answer=%s key=%s", session_id, window.number,
                answer_kind, key or "Escape")
    window_state.note_answered(session_id, window.number)
    note_user_input(session_id)
    asyncio.create_task(poke_now(session_id))
    return {"ok": True}
