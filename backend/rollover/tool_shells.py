"""Which commands of a claude end with its conversation: the shells its Bash and Monitor tools run, found in a process
table that the caller read (the rollover watch reads it with psutil, `tabs rollover` with `ps`).

When a conversation ends, Claude Code stops the commands its tools run in the background (SIGTERM to the tool's
shell and what runs under it). A command started with `nohup … &` from a tool call outlives it, since its shell has
already returned. Each tool call runs in a shell that is a direct child of claude and sources one of Claude Code's
shell snapshots, which tells it apart from claude's other children (MCP and language servers, hooks, the status line,
the `caffeinate` claude runs while it answers). If Claude Code changes that shape, nothing is counted and a rollover
ends the commands as it did before.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: What the command line of a tool's shell contains (the snapshot of the operator's shell it sources first)
TOOL_SHELL_MARK = "/shell-snapshots/snapshot-"
#: How much of a command is shown to name it
COMMAND_HEAD_CHARS = 100

# The tool's shell runs the command as `eval '<command>' < /dev/null`, with each `'` of the command written `'"'"'`.
_EVAL = re.compile(r"eval '((?:[^']|'\"'\"')*)' < /dev/null")


@dataclass(frozen=True)
class ProcessRow:
    """One row of a process table: what the judgement needs of a process."""
    pid: int
    parent_pid: int
    command_line: str
    elapsed_seconds: float | None = None


@dataclass(frozen=True)
class ToolShell:
    """A tool's shell still running under claude: its pid, how long it has run and the command it runs."""
    pid: int
    elapsed_seconds: float | None
    command: str


def is_tool_shell(command_line: str) -> bool:
    """Whether a command line is that of a shell Claude Code runs a tool call in."""
    return TOOL_SHELL_MARK in command_line


def command_of(command_line: str) -> str:
    """The command a tool's shell runs, cut to `COMMAND_HEAD_CHARS`; the start of the command line when the command
    cannot be found in it."""
    found = _EVAL.search(command_line)
    command = found.group(1).replace("'\"'\"'", "'") if found else command_line
    command = " ".join(command.split())
    return command if len(command) <= COMMAND_HEAD_CHARS else command[:COMMAND_HEAD_CHARS - 1] + "…"


def tool_shells(rows: list[ProcessRow], claude_pid: int, *, leaving_out: int | None = None) -> list[ToolShell]:
    """The tools' shells directly under `claude_pid`, oldest first, but `leaving_out` (= the shell of the call that
    asks, which ends with the conversation by design)."""
    shells = [row for row in rows
              if row.parent_pid == claude_pid and row.pid != leaving_out and is_tool_shell(row.command_line)]
    shells.sort(key=lambda row: -(row.elapsed_seconds or 0.0))
    return [ToolShell(pid=row.pid, elapsed_seconds=row.elapsed_seconds, command=command_of(row.command_line))
            for row in shells]


def own_tool_shell(rows: list[ProcessRow], pid: int) -> ProcessRow | None:
    """The tool's shell that `pid` runs under (= its nearest ancestor that is one, `pid` itself included); None when
    `pid` does not run in a tool call."""
    by_pid = {row.pid: row for row in rows}
    seen: set[int] = set()
    row = by_pid.get(pid)
    while row is not None and row.pid not in seen:
        if is_tool_shell(row.command_line):
            return row
        seen.add(row.pid)
        row = by_pid.get(row.parent_pid)
    return None


def seconds_of_elapsed(text: str) -> float | None:
    """The seconds of an elapsed time as `ps -o etime` writes it (`[[dd-]hh:]mm:ss`); None when it is not one."""
    days, _, clock = text.strip().rpartition("-")
    parts = clock.split(":")
    if not 2 <= len(parts) <= 3 or not all(part.isdigit() for part in parts) or (days and not days.isdigit()):
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return float(seconds + int(days or 0) * 86400)


def elapsed_text(seconds: float | None) -> str:
    """How long a shell has run, for a person (`2時間5分` / `5分` / `40秒`); `?` when unknown."""
    if seconds is None:
        return "?"
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}時間{minutes}分"
    return f"{minutes}分" if minutes else f"{secs}秒"
