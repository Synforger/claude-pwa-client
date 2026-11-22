"""Gives `permission_window/window_hold.py` what it types, looks and tells with, and the one line the client tells another tab
when a message it kept for it did not arrive.

The kept messages are typed through `pty_send` as the messages of a person or another tab they are (`hold`, and `releasing`
so that a window that opened again keeps them where they were). A sender that is another tab is told in one line, as the
client's own notice (the first line is the one the client's notices begin with); a sleeping sender is not woken for it, and
a sender that is gone is not told.

Used by `main.py` (imported once, at the start).
"""
from __future__ import annotations

import asyncio
import logging

import backend.jsonl.jsonl_watcher as jsonl_watcher
from backend._common.state import sessions_meta
from backend.jsonl.jsonl_predicates import CLIENT_NOTICE_OPENING
from backend.permission_window import window_hold
from backend.permission_window.window_hold import NOT_TAKEN, NO_CLAUDE, OTHER_CONVERSATION, Wiring
from backend.terminal.pty_discover import claude_in_pane
from backend.terminal.routes import pty_send

logger = logging.getLogger(__name__)

TAG = "message-not-delivered"
# How much of the text is quoted to the sender, so that it can tell which message it was.
QUOTE_CHARS = 60
_WHY = {
    NO_CLAUDE: "no claude runs in that tab any more",
    OTHER_CONVERSATION: "that tab is in another conversation now",
    NOT_TAKEN: "the tab did not take it when the window was gone",
}


async def _type_kept(session_id: str, text: str, sender_tab: str | None) -> dict:
    """Type a kept message the way it was sent (a message of a person or another tab), once."""
    return await pty_send(session_id, {"text": text, "enter": True}, None, hold=True, sender=sender_tab, releasing=True)


def _conversation_of(session_id: str) -> str | None:
    record = jsonl_watcher.get_jsonl_for(session_id)
    return record.stem if record is not None else None


async def _tab_has_claude(session_id: str) -> bool:
    return await asyncio.to_thread(claude_in_pane, session_id)


def not_delivered_envelope(receiver_title: str, text: str, reason: str) -> str:
    """The notice a tab gets when a message of its own, kept while a window was open on `receiver_title`, did not arrive."""
    quoted = " ".join(text.split())[:QUOTE_CHARS].replace('"', "'")
    return (f'{CLIENT_NOTICE_OPENING}\n<{TAG} to="{receiver_title.replace(chr(34), chr(39))}" reason="{reason}">\n'
            f'The message that begins "{quoted}" was kept while a window was open on that tab and did not arrive: '
            f'{_WHY.get(reason, reason)}. Send it again if it is still wanted.\n</{TAG}>')


async def _tell_sender(sender_tab: str, receiver_id: str, text: str, reason: str) -> None:
    # Imported here: the module of client messages imports the route of messages between tabs.
    from backend.accounts.client_message import send_to_tab  # noqa: PLC0415
    sender = sessions_meta.get(sender_tab)
    if sender is None or sender.sleep is not None:
        logger.info("window hold: the sender is gone or asleep, not told sender=%s", sender_tab)
        return
    receiver = sessions_meta.get(receiver_id)
    await send_to_tab(sender_tab, not_delivered_envelope(receiver.title if receiver is not None else receiver_id, text, reason))


window_hold.install(Wiring(send=_type_kept, tab_exists=sessions_meta.__contains__, claude_alive=_tab_has_claude,
                           conversation_of=_conversation_of, tell_sender=_tell_sender))
