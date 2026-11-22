"""Getting a message into a tab whose claude was just started: waiting until the screen is Claude's input, and making
sure the typed message was taken.

A claude reopening a conversation is ready by its hooks (`input_ready`) before it has read the conversation and drawn
its screen, and keys typed in between are lost, though the typing itself succeeds. So a woken tab is typed to only
once its pane shows Claude's screen, and what was typed is then looked for in the conversation record: a row of a
person's prompt, or, when Claude was answering, the row of the text being queued (= it is read at the turn's next
break, and shows in the input box until then). When it does not come, the pane says why: the text still waits in the input (Enter was lost) or it is
gone (it was typed too early). A text that waits gets Enter again every few seconds until it is taken (= a claude that has
just read a long conversation on a busy machine drops keys for a while, sometimes for more than 20 seconds), and a text that is gone is typed once more; both stop after `RESCUE_SEC`.
A text still waiting in the input when the rescue stops is cleared from it: the caller then tells the sender the message
was not taken, and a text left there would go in with the next Enter, on top of the sender's second send.

A launch still starting is waited for before anything is typed. Typing then would hand the text to the launch's held
messages (`first_message.hold_while_launching`), and the rescue typing it again would hold it a second time.

A tab with no claude at all is started by the typing itself (`first_message.launch_with_first_message`): the text goes
to the launch, as its first message or held to be typed once the claude is up, and `pty_send` answers `launched`. From
then on the launch owns the text and this module only watches the record for it (`_taken_by_launch`): the record of a
conversation that has not begun shows nothing yet, and a rescue that read that as "gone" typed the text a second time,
which the new conversation got twice.

A stop of the backend ends every wait here (`_internal/stop_signal.py`), since the responses that wait get 3 seconds
and these wait for minutes. `deliver_to_woken` raises `StoppedBeforeTyping` when nothing of the text was typed yet (= the
sender may send it again), and `BackendStopping` once it was (= it may have arrived, and the rescue stops where it is).

Used by `routes/agent_messages.py` for a tab it had to wake (`deliver_to_woken`, `wait_for_claude_screen`). A tab that
was already running keeps the plain `pty_send`: its answer in the middle of a turn writes no row, so no row proves
nothing there.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from backend._internal.stop_signal import BackendStopping, until_stop
from backend.permission_window import window_answer
from backend.permission_window.window_judgement import Caller, WindowInTheWay
from backend.terminal import input_ready
from backend.terminal.ansi_text import strip_ansi
from backend.terminal.confirm import CONFIRM_TIMEOUT_SEC, wait_taken_row, wait_text_row
from backend.terminal.pane_order import in_typing_order
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


# What `deliver_to_woken` says besides True (the record shows the message) and False (it was not taken): the message is kept
# while a window is open, and typed when the window is gone.
HELD = "held"


class StoppedBeforeTyping(BackendStopping):
    """The backend was asked to stop before any of the text was typed."""


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
    return await wait_taken_row(jsonl_path_for_session(session_id), initial_pos, timeout, text,
                                follow=lambda: jsonl_path_for_session(session_id))


def _record_end(session_id: str) -> int:
    path = jsonl_path_for_session(session_id)
    try:
        return path.stat().st_size if path is not None else 0
    except OSError:
        return 0


async def deliver_to_woken(session_id: str, text: str, *, hold: bool = True, sender: str | None = None,
                           send_id: str | None = None) -> bool | str:
    """Type `text` into a tab that was just started and make sure it was taken. True when the record shows the message
    (maybe after the rescue: Enter again while the text waits in the input, typing it once more when it is gone); `HELD`
    when a window is open and the message is kept to be typed when it is gone (`hold` says whether a window keeps it
    or refuses it, as for `pty_send`; `sender` is the tab and `send_id` the screen's send to tell if it does not arrive); False when it did not
    within `RESCUE_SEC`, or the launch in flight was given up, which is for the caller to refuse. A text that the typing
    handed to a launch is not typed again (`_taken_by_launch`). Raises `StoppedBeforeTyping` when the backend stops while
    the launch is waited for, and `BackendStopping` when it stops after the typing."""
    if input_ready.launching(session_id):
        try:
            launched = await until_stop(_wait_for_launch(session_id))
        except BackendStopping:
            raise StoppedBeforeTyping from None
        if not launched:
            return False
    record = jsonl_path_for_session(session_id)
    initial_pos = _record_end(session_id)
    result = await pty_send(session_id, {"text": text, "enter": True}, None, hold=hold, sender=sender, send_id=send_id)
    if not result.get("ok"):
        return False
    if result.get("held"):
        return HELD     # kept while a window is open: `window_hold` types it, once, when the window is gone
    return await until_stop(_taken_after_typing(session_id, record, initial_pos, text, result, hold, sender, send_id))


async def _wait_for_launch(session_id: str) -> bool:
    """Wait for the launch in flight to end and for the screen of its claude. False when the launch was given up."""
    if not await input_ready.wait_launched(session_id):
        logger.warning("receipt: the launch was given up before the message could be typed session=%s", session_id)
        return False
    await wait_for_claude_screen(session_id)
    return True


async def _taken_after_typing(session_id: str, record: Path | None, initial_pos: int, text: str, result: dict, hold: bool,
                              sender: str | None, send_id: str | None) -> bool | str:
    """Wait for the row of `text`, which `pty_send` answered `result` for: from the launch it was handed to, or from
    the typing itself, with the rescue when the row does not come."""
    if result.get("launched"):
        return await _taken_by_launch(session_id, record, initial_pos, text)
    if result.get("confirmed") or await _taken(session_id, initial_pos, TAKEN_WAIT_SEC - CONFIRM_TIMEOUT_SEC, text):
        return True
    return await _rescue(session_id, initial_pos, text, hold, sender, send_id)


async def _taken_by_launch(session_id: str, record: Path | None, initial_pos: int, text: str) -> bool:
    """Watch for `text`, which the typing handed to the tab's launch (= its first message, or held to be typed once the
    claude is up: both are the launch's to type, and a second typing would deliver it twice). True when the record shows
    the text itself (= not the envelope a tier tab starts with); False when the launch was given up, or the text did not
    come within the screen wait and the rescue the held message gets. `record` and `initial_pos` are where the tab's
    record stood before the typing (= None while the conversation has not begun)."""
    if not await input_ready.wait_launched(session_id):
        logger.warning("receipt: the launch was given up before the message was taken session=%s", session_id)
        return False
    return await wait_text_row(record, initial_pos, SCREEN_WAIT_SEC + RESCUE_SEC, text,
                               follow=lambda: jsonl_path_for_session(session_id))


async def _rescue(session_id: str, initial_pos: int, text: str, hold: bool, sender: str | None,
                  send_id: str | None) -> bool | str:
    """Put right a typed text whose row did not come: Enter while it waits in the input, one more typing once it is
    gone, then wait `ENTER_AGAIN_SEC` for the row, until `RESCUE_SEC` has passed. A text that still waits then is
    cleared from the input, so that the refusal the caller gives holds. No key is typed while a window is on the screen
    (= its Enter would take the window's first choice): the Enter waits for the window, and a typing again is kept like
    any other (`HELD`)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + RESCUE_SEC
    typed_again = False
    check = window_answer.check_before_typing(session_id, Caller.MESSAGE, releasing=True)
    while loop.time() < deadline:
        if text_waits_in_input(await asyncio.to_thread(pane_text, session_id), text):
            logger.info("receipt: the message waits in the input, sending Enter session=%s", session_id)
            try:
                await in_typing_order(session_id, lambda: (check(), tmux_send_keys(session_id, enter=True))[1])
            except WindowInTheWay:
                logger.info("receipt: a window is open, no Enter for the message session=%s", session_id)
        elif not typed_again:
            logger.info("receipt: the message is gone, typing it again session=%s", session_id)
            typed_again = True
            again = await pty_send(session_id, {"text": text, "enter": True}, None, hold=hold, sender=sender, send_id=send_id)
            if not again.get("ok"):
                return False
            if again.get("held"):
                return HELD
        if await _taken(session_id, initial_pos, ENTER_AGAIN_SEC, text):
            return True
    if text_waits_in_input(await asyncio.to_thread(pane_text, session_id), text):
        logger.warning("receipt: the message was not taken in %.0fs, clearing it from the input session=%s",
                       RESCUE_SEC, session_id)
        try:
            await in_typing_order(session_id, lambda: (check(), tmux_send_keys(session_id, key="C-u"))[1])
        except WindowInTheWay:
            logger.info("receipt: a window is open, the message is left in the input session=%s", session_id)
    return False
