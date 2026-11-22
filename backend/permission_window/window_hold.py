"""The messages kept while a window is open, and typed in order once the screen shows the input box again.

A text typed into the pane while a window (a permission, a question, a plan approval) is on the screen is not read as a
message: its Enter takes the window's first choice and the text is lost. So the send keeps a message of a person and of
another tab here instead, answers `{"ok": true, "held": "window"}`, and the messages are typed in the order they were
kept once the screen has shown the input box on two looks in a row (`window_judgement.INPUT_LOOKS_TO_RELEASE`: not right
after an answer, and not on the word of a hook).

What is kept belongs to the conversation it was sent into, and lives in a file (600) of the state folder so that it
survives a restart. It is dropped, and its sender told that it did not arrive, when the conversation is another one, the
tab is closed or no claude runs in it. The patrol is the detector's look at each tab (`terminal/prompt_detector_loop.py`),
so a message is released or dropped whether or not the client remembers a window.

The functions that type, tell and look are given by `terminal/routes.py` and `routes/agent_messages.py` (`install`): this
package sits under the terminal's layer and cannot import it.

Used by `terminal/routes.py`, `terminal/prompt_detector_loop.py` and `routes/agent_messages.py`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass

from backend._common.paths import WINDOW_HOLD_PATH
from backend._common.state import jsonl_event_broadcaster
from backend.permission_window import window_state
from backend.permission_window.window_judgement import INPUT_LOOKS_TO_RELEASE

logger = logging.getLogger(__name__)

HELD = "window"
# Why a kept message did not arrive, as the sender is told.
NO_CLAUDE = "no_claude"
OTHER_CONVERSATION = "other_conversation"
NOT_TAKEN = "not_taken"


@dataclass
class Kept:
    """One message kept: its text, the screen's id of the send (a person's), the tab that sent it (another tab's), the
    conversation it was sent into and when."""
    text: str
    send_id: str | None
    sender_tab: str | None
    conversation: str | None
    kept_at: float


@dataclass
class Wiring:
    """What `window_hold` is given: types a text (`send(session_id, text, sender_tab)` → the answer of `pty_send`), says
    whether the tab exists, whether a claude runs in it, which conversation it is in, and tells another tab that its
    message did not arrive."""
    send: Callable[[str, str, str | None], Awaitable[dict]]
    tab_exists: Callable[[str], bool]
    claude_alive: Callable[[str], Awaitable[bool]]
    conversation_of: Callable[[str], str | None]
    tell_sender: Callable[[str, str, str, str], Awaitable[None]]


_kept: dict[str, list[Kept]] = {}
_typers: dict[str, asyncio.Task] = {}
_wiring: Wiring | None = None
_loaded = False


def install(wiring: Wiring) -> None:
    """Give the functions this package types, tells and looks with."""
    global _wiring
    _wiring = wiring


def load() -> None:
    """Read the kept messages from the file. Called once, when the backend starts (the first use reads it if not)."""
    global _loaded
    _loaded = True
    try:
        stored = json.loads(WINDOW_HOLD_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except (OSError, ValueError):
        logger.warning("window hold: the kept messages could not be read, starting with none: %s", WINDOW_HOLD_PATH)
        return
    for session_id, entries in stored.items():
        _kept[session_id] = [Kept(**entry) for entry in entries]
    logger.info("window hold: read the kept messages of %d tabs", len(_kept))


def _ensure_loaded() -> None:
    if not _loaded:
        load()


def has_kept(session_id: str) -> bool:
    """Whether the tab has messages kept, or typing them now: a message sent now goes behind them."""
    _ensure_loaded()
    typing = _typers.get(session_id)
    return bool(_kept.get(session_id)) or (typing is not None and not typing.done())


def keep(session_id: str, text: str, send_id: str | None = None, sender_tab: str | None = None) -> None:
    """Keep `text` for the tab, after the ones kept before it."""
    _ensure_loaded()
    assert _wiring is not None
    _kept.setdefault(session_id, []).append(
        Kept(text, send_id, sender_tab, _wiring.conversation_of(session_id), time.time()))
    _save()
    logger.info("window hold: kept a message session=%s kept=%d", session_id, len(_kept[session_id]))


async def patrol(session_id: str) -> None:
    """One look at the tab's kept messages (= the detector's look at the tab just taken): drop what cannot arrive, and start
    typing them when the screen has shown the input box long enough."""
    _ensure_loaded()
    if not _kept.get(session_id):
        return
    assert _wiring is not None
    if not _wiring.tab_exists(session_id) or not await _wiring.claude_alive(session_id):
        await drop(session_id, NO_CLAUDE)
        return
    await _drop_of_other_conversations(session_id)
    if _kept.get(session_id) and window_state.input_looks(session_id) >= INPUT_LOOKS_TO_RELEASE:
        release(session_id)


def release(session_id: str) -> asyncio.Task:
    """Start typing the tab's kept messages in order (= the task that does so, one at a time per tab)."""
    typing = _typers.get(session_id)
    if typing is None or typing.done():
        typing = asyncio.get_running_loop().create_task(_type_kept(session_id))
        _typers[session_id] = typing
        typing.add_done_callback(lambda done: _typers.pop(session_id, None) if _typers.get(session_id) is done else None)
    return typing


async def drop(session_id: str, reason: str) -> None:
    """Drop what is kept for the tab and tell the senders that it did not arrive."""
    entries = _kept.pop(session_id, [])
    if entries:
        _save()
        logger.info("window hold: dropped %d messages session=%s reason=%s", len(entries), session_id, reason)
    for entry in entries:
        await _tell_not_arrived(session_id, entry, reason)


async def _drop_of_other_conversations(session_id: str) -> None:
    assert _wiring is not None
    current = _wiring.conversation_of(session_id)
    entries = _kept.get(session_id, [])
    gone = [entry for entry in entries if entry.conversation is not None and current is not None
            and entry.conversation != current]
    if not gone:
        return
    _kept[session_id] = [entry for entry in entries if entry not in gone]
    _save()
    logger.info("window hold: dropped %d messages of an earlier conversation session=%s", len(gone), session_id)
    for entry in gone:
        await _tell_not_arrived(session_id, entry, OTHER_CONVERSATION)


async def _type_kept(session_id: str) -> None:
    """Type the tab's kept messages one by one. A message is taken off the file before it is typed (= typed once, not
    twice, if the backend stops meanwhile); one that finds a window again goes back to the front and the rest wait."""
    assert _wiring is not None
    while _kept.get(session_id):
        entry = _kept[session_id].pop(0)
        _save()
        try:
            result = await _wiring.send(session_id, entry.text, entry.sender_tab)
        except Exception:
            # The tab may have been closed meanwhile: the message did not arrive, and the next one is still tried.
            logger.exception("window hold: a kept message could not be typed session=%s", session_id)
            result = {"ok": False}
        if result.get("held"):
            _kept.setdefault(session_id, []).insert(0, entry)
            _save()
            return
        if not result.get("ok"):
            logger.error("window hold: a kept message was not taken session=%s reason=%s", session_id, result.get("reason"))
            await _tell_not_arrived(session_id, entry, NOT_TAKEN)
    _kept.pop(session_id, None)


async def _tell_not_arrived(session_id: str, entry: Kept, reason: str) -> None:
    """Tell the sender: a person's screen marks its bubble as not sent and puts the text back; another tab is told in one line
    by the client (a sleeping tab is not woken)."""
    assert _wiring is not None
    if entry.send_id is not None:
        jsonl_event_broadcaster.publish(session_id, {"type": "send_failed", "sid": session_id, "send_id": entry.send_id})
    if entry.sender_tab is not None:
        try:
            await _wiring.tell_sender(entry.sender_tab, session_id, entry.text, reason)
        except Exception:
            # The sender may be gone too; there is nobody left to tell.
            logger.exception("window hold: the sender could not be told session=%s sender=%s", session_id, entry.sender_tab)


def _save() -> None:
    """Write the kept messages to the file (600, the old file replaced whole)."""
    stored = {session_id: [asdict(entry) for entry in entries] for session_id, entries in _kept.items() if entries}
    tmp = WINDOW_HOLD_PATH.with_name(f"{WINDOW_HOLD_PATH.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(stored, ensure_ascii=False))
        os.replace(tmp, WINDOW_HOLD_PATH)
    except OSError:
        tmp.unlink(missing_ok=True)
        logger.warning("window hold: the kept messages could not be written (a restart will not find them): %s",
                       WINDOW_HOLD_PATH, exc_info=True)
