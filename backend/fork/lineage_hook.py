"""Runs the command the client's configuration names (`lineage_hook`) once a new conversation record has been written,
before that conversation is opened. The command is given the new conversation's id (`{session}`) and the id of the
conversation it continues (`{from_session}`), so that whatever follows a conversation by its id can follow it into
the new one.

Used by `lineage.py` after it writes a record. Nothing is run when the configuration has no `lineage_hook`.
"""
from __future__ import annotations

import logging
import os
import subprocess

import backend._common.config as config

logger = logging.getLogger(__name__)

# How long the command may run before the new conversation is given up.
LINEAGE_HOOK_TIMEOUT_SEC = 30.0
# How many characters of the command's last line of complaint are kept in the log.
REASON_CHARS = 300


class LineageHookFailed(Exception):
    """The configured command did not succeed; the new conversation must not be opened."""


def carry_over(new_session_id: str, from_session_id: str) -> None:
    """Run the configured command for a new conversation record. Returns at once when none is configured; raises
    `LineageHookFailed` (= with the reason) when the command cannot run, does not finish in time or does not exit 0.
    Blocks, so a caller on the event loop runs it in a thread."""
    template = config.LINEAGE_HOOK
    if not template:
        return
    names = {"session": new_session_id, "from_session": from_session_id}
    argv = []
    for word in template:
        for name, value in names.items():
            word = word.replace("{" + name + "}", value)
        argv.append(os.path.expanduser(word))
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=LINEAGE_HOOK_TIMEOUT_SEC)
    except subprocess.TimeoutExpired as error:
        raise LineageHookFailed(f"did not finish in {LINEAGE_HOOK_TIMEOUT_SEC:.0f}s") from error
    except OSError as error:
        raise LineageHookFailed(f"could not run: {error}") from error
    if done.returncode != 0:
        lines = [line.strip() for line in done.stderr.splitlines() if line.strip()]
        reason = (lines[-1] if lines else "no message")[:REASON_CHARS]
        raise LineageHookFailed(f"exit {done.returncode}: {reason}")
    logger.info("lineage hook: carried over from=%s to=%s", from_session_id, new_session_id)
