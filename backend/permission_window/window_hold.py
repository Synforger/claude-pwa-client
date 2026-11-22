"""The messages kept while a window is open, and typed in order once none is.

A text typed into the pane while a permission window, a question or a plan approval is open is not read as a message:
its Enter confirms the window's first choice, and the text is lost (measured: a message of another tab typed there
approved a command and vanished). So `pty_send` hands the text here instead (= `hold_if_open`, answered
`{"ok": true, "held": "window"}`), and it is typed through `pty_send` again once the tab has nothing open. Texts kept
before the window closed stay in front of any that arrive while they are being typed, so the order is the order sent.

The sender is given by `terminal/routes.py` (`install`): this package sits under the terminal's layer and cannot import it.

Used by `terminal/routes.py`.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from backend._common.state import jsonl_event_broadcaster
from backend.permission_window import window_state

logger = logging.getLogger(__name__)

HELD = "window"

# What was kept, per tab, as `(text, the screen's id of the send)` in the order sent; and the task that types them.
_kept: dict[str, list[tuple[str, str | None]]] = {}
_typers: dict[str, asyncio.Task] = {}
_sender: Callable[[str, str], Awaitable[dict]] | None = None


def install(sender: Callable[[str, str], Awaitable[dict]]) -> None:
    """Give the function that types a text into a tab (`sender(session_id, text)` → the answer of `pty_send`), and have
    the kept texts typed when a window closes."""
    global _sender
    _sender = sender
    window_state.add_close_listener(release)


def hold_if_open(session_id: str, text: str, send_id: str | None = None) -> dict | None:
    """Keep `text` when the tab has a window open (or kept texts that are still to be typed), → the send's answer.
    None when nothing is in the way (= the caller types it). The typing of the kept texts passes through here too and
    is held only by a window."""
    typing = _typers.get(session_id)
    in_typer = typing is not None and asyncio.current_task() is typing
    if not window_state.is_holding(session_id) and (in_typer or not _pending(session_id)):
        return None
    _kept.setdefault(session_id, []).append((text, send_id))
    logger.info("window hold: kept a message session=%s kept=%d", session_id, len(_kept[session_id]))
    return {"ok": True, "held": HELD}


def _pending(session_id: str) -> bool:
    typing = _typers.get(session_id)
    return bool(_kept.get(session_id)) or (typing is not None and not typing.done())


def release(session_id: str) -> None:
    """A window of the tab closed: type the kept texts when nothing else is open. Only starts the typing (= it runs on
    the event loop; with none running, as in a test, the texts stay kept)."""
    if not _kept.get(session_id) or window_state.is_holding(session_id):
        return
    typing = _typers.get(session_id)
    if typing is not None and not typing.done():
        return
    try:
        task = asyncio.get_running_loop().create_task(_type_kept(session_id))
    except RuntimeError:
        logger.warning("window hold: no event loop to type the kept messages session=%s", session_id)
        return
    _typers[session_id] = task
    task.add_done_callback(lambda done: _typers.pop(session_id, None) if _typers.get(session_id) is done else None)


async def _type_kept(session_id: str) -> None:
    """Type the tab's kept texts one by one, stopping when a window opens again (= the rest wait for it)."""
    assert _sender is not None
    while _kept.get(session_id) and not window_state.is_holding(session_id):
        text, send_id = _kept[session_id].pop(0)
        try:
            result = await _sender(session_id, text)
        except Exception:
            # The tab may have been closed meanwhile; the next kept text is still tried.
            logger.exception("window hold: a kept message could not be typed session=%s", session_id)
            result = {"ok": False}
        if not result.get("ok"):
            logger.error("window hold: a kept message was not taken session=%s reason=%s", session_id, result.get("reason"))
            if send_id is not None:
                jsonl_event_broadcaster.publish(session_id, {"type": "send_failed", "sid": session_id, "send_id": send_id})
    if not _kept.get(session_id):
        _kept.pop(session_id, None)
