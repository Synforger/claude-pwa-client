"""Reads the visible screen of a pane from tmux.

Read side of the connect-time snapshot: one tmux invocation, blocking. Callers on the event
loop run it through `asyncio.to_thread`. The bytes that paint the screen are built by
`screen_snapshot`; `connect_snapshot` calls this module.
"""
from __future__ import annotations

import logging

from backend.terminal import runner
from backend.terminal.screen_snapshot import REPORT_FORMAT, PaneScreen, parse_screen_report

logger = logging.getLogger(__name__)

# A loaded machine answers a tmux command in a few hundred milliseconds at worst, but a
# stuck server must not hold a connection for long: the connection then goes on without
# a snapshot.
CAPTURE_TIMEOUT_SEC = 3.0


def capture_pane_screen(session_id: str) -> PaneScreen | None:
    """Returns the visible screen of the pane of `session_id`, or None when it cannot be read.

    The cursor report and the rows come from one tmux invocation (two commands joined by
    `;`), which the server runs back to back: a repaint between two separate invocations
    would leave the cursor on a row that no longer matches. Scrollback is not captured:
    replaying history once broke the screen, because cursor controls inside it do not match
    the state of a new terminal. Rows are captured with `-N`: without it tmux drops the
    blank cells at the end of a row, which loses a background colour that runs to the
    edge (a highlighted line). The log says why a capture failed.
    """
    if not runner.USE_TMUX_WRAP:
        logger.info("screen capture skipped: tmux is not in use session=%s", session_id)
        return None
    target = runner._tmux_session_name(session_id)
    result = runner._run_tmux(
        "display-message", "-p", "-t", target, REPORT_FORMAT,
        ";",
        "capture-pane", "-p", "-e", "-N", "-t", target,
        timeout=CAPTURE_TIMEOUT_SEC,
    )
    if result is None:
        logger.warning("screen capture failed: tmux did not answer in %.1fs session=%s",
                       CAPTURE_TIMEOUT_SEC, session_id)
        return None
    if result.returncode != 0:
        logger.info("screen capture failed: tmux rc=%s (%s) session=%s", result.returncode,
                    result.stderr.decode("utf-8", errors="replace").strip(), session_id)
        return None
    screen = parse_screen_report(result.stdout.decode("utf-8", errors="replace"))
    if screen is None:
        logger.warning("screen capture failed: unreadable report session=%s", session_id)
    return screen
