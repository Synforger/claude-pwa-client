"""Sends the pane's current screen as the first output of a newly attached terminal.

Called by `pty_socket` after the session exists and before live output starts to flow. The
terminal sends its size first; the screen is captured only once tmux runs at that size, so
the rows fit the terminal that paints them. When the screen cannot be captured the
connection goes on without one and the terminal is told so (`SNAPSHOT_NONE_MESSAGE`),
which makes it ask the program in the pane to repaint, as it did before snapshots existed.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from backend.terminal.runner import PtySession
from backend.terminal.screen_capture import capture_pane_screen
from backend.terminal.screen_snapshot import PaneScreen, build_snapshot

logger = logging.getLogger(__name__)

# How long to wait for the terminal's first size before capturing at whatever size tmux
# has. The terminal sends it in the same turn as it opens the socket, so this only runs
# out for a client that sends none.
RESIZE_WAIT_SEC = 1.5
# tmux applies a size a moment after the client asked for it. The capture is retried until
# the pane has the size the terminal asked for, this often, this many times.
SIZE_SETTLE_POLL_SEC = 0.05
SIZE_SETTLE_ATTEMPTS = 20

# Text frame sent instead of a snapshot; the terminal then asks for a repaint itself.
SNAPSHOT_NONE_MESSAGE = {"type": "snapshot", "status": "none"}


def drain_output_queue(session: PtySession) -> int:
    """Drops what the pane printed while no terminal was attached. Returns the chunk count.

    These chunks are incremental repaints (header redraws, cursor blinks) of a screen the
    new terminal has not seen. Played onto a fresh terminal they stack the same screen two
    or three times, so the snapshot replaces them.
    """
    return drop_oldest_output(session, session.output_queue.qsize())


def drop_oldest_output(session: PtySession, count: int) -> int:
    """Drops up to `count` of the oldest queued chunks. Returns how many were dropped."""
    dropped = 0
    while dropped < count:
        try:
            session.output_queue.get_nowait()
            dropped += 1
        except asyncio.QueueEmpty:
            break
    return dropped


async def send_connect_snapshot(
    ws: WebSocket,
    session: PtySession,
    resized: asyncio.Future[tuple[int, int]],
    input_pump: asyncio.Task,
) -> None:
    """Sends the first output of a connection. Never raises: a failure means no snapshot.

    `resized` receives `(rows, cols)` when the terminal's first size has reached tmux;
    `input_pump` is the task that reads the terminal's messages, which ends when the
    client leaves.
    """
    dropped = drain_output_queue(session)
    if dropped:
        logger.info("connect snapshot: dropped %d chunks from while the client was away session=%s",
                    dropped, session.session_id)
    screen = None
    try:
        size = await _wait_for_size(resized, input_pump, session.session_id)
        screen = await _capture_settled(session, size)
    except Exception:
        logger.exception("connect snapshot: capture failed, connecting without one session=%s", session.session_id)
    try:
        if ws.client_state != WebSocketState.CONNECTED:
            return
        if screen is None:
            await ws.send_text(json.dumps(SNAPSHOT_NONE_MESSAGE))
        else:
            await ws.send_bytes(build_snapshot(screen))
    except (WebSocketDisconnect, RuntimeError):
        # benign: the client left while the snapshot was on its way
        logger.debug("connect snapshot: client left before it was sent session=%s", session.session_id)


async def _wait_for_size(
    resized: asyncio.Future[tuple[int, int]], input_pump: asyncio.Task, session_id: str,
) -> tuple[int, int] | None:
    """Returns the terminal's first `(rows, cols)`, or None when none arrives in time."""
    await asyncio.wait({resized, input_pump}, timeout=RESIZE_WAIT_SEC, return_when=asyncio.FIRST_COMPLETED)
    if resized.done():
        return resized.result()
    logger.info("connect snapshot: no terminal size within %.1fs, capturing at the current size session=%s",
                RESIZE_WAIT_SEC, session_id)
    return None


async def _capture_settled(session: PtySession, size: tuple[int, int] | None) -> PaneScreen | None:
    """Captures the screen once the pane has `size` (any size when `size` is None).

    Output that was queued before a capture began is already on the captured screen, so it
    is dropped once the capture is taken; what the pane prints during and after the capture
    stays queued as live output. Nothing is dropped when there is no capture, since then the
    queue is all the terminal will see. If the pane never reaches `size` the last capture is
    used; the program in the pane repaints when tmux resizes it.
    """
    screen = None
    for _ in range(SIZE_SETTLE_ATTEMPTS):
        already_printed = session.output_queue.qsize()
        screen = await asyncio.to_thread(capture_pane_screen, session.session_id)
        if screen is None:
            return None
        if size is None or (screen.height, screen.width) == size:
            drop_oldest_output(session, already_printed)
            return screen
        await asyncio.sleep(SIZE_SETTLE_POLL_SEC)
    logger.warning("connect snapshot: pane stayed %dx%d, terminal asked for %dx%d session=%s",
                   screen.width, screen.height, size[1], size[0], session.session_id)
    drop_oldest_output(session, already_printed)
    return screen
