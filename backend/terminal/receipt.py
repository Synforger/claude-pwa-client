"""Getting a message into a tab whose claude was just started: waiting until the screen is Claude's input, and making
sure the typed message was taken.

A claude reopening a conversation is ready by its hooks (`input_ready`) before it has read the conversation and drawn
its screen, and keys typed in between are lost, though the typing itself succeeds. So a woken tab is typed to only
once its pane shows Claude's screen, and what was typed is then looked for in the conversation record: a row of a
person's prompt, or, when Claude was answering, the row of the text being queued (= it is read at the turn's next
break, and shows in the input box until then). When it does not come, the pane says why: the text still waits in the input (Enter was lost) or it is
gone (it was typed too early). A text that waits gets Enter again every few seconds until it is taken (= a claude that has
just read a long conversation on a busy machine drops keys for a while, sometimes for more than 20 seconds), and a text that is gone is typed once more; both stop after `RESCUE_SEC`.

A launch still starting is waited for before anything is typed. Typing then would hand the text to the launch's held
messages (`first_message.hold_while_launching`), and the rescue typing it again would hold it a second time.

Used by `routes/agent_messages.py` for a tab it had to wake (`deliver_to_woken`, `wait_for_claude_screen`). A tab that
was already running keeps the plain `pty_send`: its answer in the middle of a turn writes no row, so no row proves
nothing there.
"""
from __future__ import annotations

import asyncio
import logging

from backend.terminal import input_ready
from backend.terminal.ansi_text import strip_ansi
from backend.terminal.confirm import CONFIRM_TIMEOUT_SEC, wait_taken_row
from backend.terminal.prompt_detector import claude_tui_owns_screen
from backend.terminal.routes import pty_send
from backend.terminal.runner import capture_pane_ansi_tail, jsonl_path_for_session, tmux_send_keys

logger = logging.getLogger(__name__)

# How long a started claude gets to show its screen, and how often the pane is looked at.
SCREEN_WAIT_SEC = 20.0
SCREEN_LOOK_SEC = 1.0
# How long, after typing, the row of the message is waited for (= the confirmation of `pty_send` is part of it).
TAKEN_WAIT_SEC = 10.0
# How often a text left in the input gets Enter again, and how long the rescue goes on before the message is given up.
ENTER_AGAIN_SEC = 5.0
RESCUE_SEC = 120.0
# How much of the typed message is looked for in the pane, and what the TUI shows for a long paste it has not expanded.
HEAD_CHARS = 30
PASTE_PLACEHOLDER = "[Pasted text #"


def pane_text(session_id: str) -> str:
    """The tail of the tab's pane as plain text, empty when it cannot be read. Blocks."""
    return strip_ansi(capture_pane_ansi_tail(session_id) or "")


async def wait_for_claude_screen(session_id: str) -> bool:
    """Wait until the tab's pane ends in Claude's screen (= its input box and status bar). False when it does not within
    `SCREEN_WAIT_SEC`."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + SCREEN_WAIT_SEC
    while True:
        if claude_tui_owns_screen(await asyncio.to_thread(pane_text, session_id)):
            return True
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(SCREEN_LOOK_SEC)


def text_waits_in_input(pane: str, text: str) -> bool:
    """Whether the message typed is still in the input box: its beginning is on the screen, or the TUI shows the
    placeholder of a long paste it did not send."""
    head = " ".join(text.split())[:HEAD_CHARS]
    return PASTE_PLACEHOLDER in pane or (bool(head) and head in " ".join(pane.split()))


async def _taken(session_id: str, initial_pos: int, timeout: float, text: str) -> bool:
    path = jsonl_path_for_session(session_id)
    return path is not None and await wait_taken_row(path, initial_pos, timeout, text)


def _record_end(session_id: str) -> int:
    path = jsonl_path_for_session(session_id)
    try:
        return path.stat().st_size if path is not None else 0
    except OSError:
        return 0


async def deliver_to_woken(session_id: str, text: str) -> bool:
    """Type `text` into a tab that was just started and make sure it was taken. True when the record shows the message
    (maybe after the rescue: Enter again while the text waits in the input, typing it once more when it is gone); False
    when it did not within `RESCUE_SEC`, or the launch in flight was given up, which is for the caller to refuse."""
    if input_ready.launching(session_id):
        if not await input_ready.wait_launched(session_id):
            logger.warning("receipt: the launch was given up before the message could be typed session=%s", session_id)
            return False
        await wait_for_claude_screen(session_id)
    initial_pos = _record_end(session_id)
    result = await pty_send(session_id, {"text": text, "enter": True}, None)
    if not result.get("ok"):
        return False
    if result.get("confirmed") or await _taken(session_id, initial_pos, TAKEN_WAIT_SEC - CONFIRM_TIMEOUT_SEC, text):
        return True
    return await _rescue(session_id, initial_pos, text)


async def _rescue(session_id: str, initial_pos: int, text: str) -> bool:
    """Put right a typed text whose row did not come: Enter while it waits in the input, one more typing once it is
    gone, then wait `ENTER_AGAIN_SEC` for the row, until `RESCUE_SEC` has passed."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + RESCUE_SEC
    typed_again = False
    while loop.time() < deadline:
        if text_waits_in_input(await asyncio.to_thread(pane_text, session_id), text):
            logger.info("receipt: the message waits in the input, sending Enter session=%s", session_id)
            tmux_send_keys(session_id, enter=True)
        elif not typed_again:
            logger.info("receipt: the message is gone, typing it again session=%s", session_id)
            typed_again = True
            if not (await pty_send(session_id, {"text": text, "enter": True}, None)).get("ok"):
                return False
        if await _taken(session_id, initial_pos, ENTER_AGAIN_SEC, text):
            return True
    return False
