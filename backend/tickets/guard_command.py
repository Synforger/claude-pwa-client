"""Run one of the guard's commands that the configuration lists for the tickets, and say what it answered.

A command is a list of words with `{name}` places, as `agent_message_check` is. A place whose value is empty is left out
together with the `--flag` word before it (= `--typed-in {typed_in}` is not passed when no session typed the operator's
words), so that no flag is called with nothing after it. `{text_file}` is a private file holding the text to judge.
A stop of the backend ends the wait for a command (`BackendStopping`, `_internal/stop_signal.py`). Called by `ticket_checks.py`.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import NamedTuple

from backend._common import config as _config
from backend._internal.stop_signal import until_stop
from backend.routes.agent_messages import CHECK_TIMEOUT_SEC

logger = logging.getLogger(__name__)


class CommandResult(NamedTuple):
    """`status` is the exit code, or None when the command could not run or did not finish; `stdout` is what it printed;
    `reason` is the last line it wrote on stderr (empty when it wrote none)."""

    status: int | None
    stdout: str
    reason: str


def argv_for(command: list[str], names: dict[str, str]) -> list[str]:
    """The words of `command` with every `{name}` replaced by its value, and a place with an empty value left out with
    the flag before it."""
    argv: list[str] = []
    for index, word in enumerate(command):
        if any(not value and "{" + name + "}" in word for name, value in names.items()):
            previous = command[index - 1] if index else ""
            if previous.startswith("--") and "{" not in previous and argv:
                argv.pop()
            continue
        for name, value in names.items():
            word = word.replace("{" + name + "}", value)
        argv.append(os.path.expanduser(word))
    return argv


def _write_private(text: str) -> Path:
    uploads = Path(_config.UPLOADS_TMP)
    uploads.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix="ticket-text-", suffix=".txt", dir=uploads)   # mode 0600
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(text)
    return Path(name)


async def run_command(command: list[str], names: dict[str, str], text: str | None = None) -> CommandResult:
    """Run `command` once. `text`, when given, is written to a private file named by `{text_file}` for the run. When the
    backend stops meanwhile `BackendStopping` is raised: the command goes on in its thread and its answer is not read, and
    nothing is changed on the strength of a check that did not finish."""
    scratch = _write_private(text) if text is not None else None
    try:
        argv = argv_for(command, {**names, **({"text_file": str(scratch)} if scratch else {})})
        done = await until_stop(asyncio.to_thread(subprocess.run, argv, capture_output=True, text=True,
                                                  timeout=CHECK_TIMEOUT_SEC))
    except subprocess.TimeoutExpired:
        return CommandResult(None, "", "the check did not finish in time")
    except OSError as error:
        logger.warning("ticket check could not run: %s", error)
        return CommandResult(None, "", "the check could not run")
    finally:
        if scratch is not None:
            scratch.unlink(missing_ok=True)
    lines = [line.strip() for line in done.stderr.splitlines() if line.strip()]
    return CommandResult(done.returncode, done.stdout, lines[-1] if lines else "")
