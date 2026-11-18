"""The notice the client sends a conversation that is past its rollover line but is not asked to close, because its
tools run commands in the background that the end of the conversation would stop. The first line is the one the
client's own notices begin with, so a reader can tell the operator did not type it; the block names the reason, the
context and the line, and lists the commands.

Used by `rollover.py`.
"""
from __future__ import annotations

from backend.jsonl.jsonl_predicates import CLIENT_NOTICE_OPENING as OPENING
from backend.rollover.tool_shells import ToolShell

TAG = "rollover-held"

_INTRO = ("This conversation is past its rollover line, but the client does not ask it to close while its tools run "
          "these commands in the background, since the end of the conversation would stop them:")
_OUTRO = ("Ending them is yours to decide. A command that must outlive the conversation is started from a plain Bash "
          "call as `nohup <command> > <log> 2>&1 &`; stop the background one only if it may stop. Once none runs, the "
          "client asks this conversation to close at its next look.")


def _plain(text: str) -> str:
    """One line of `text` that cannot open or close the notice's block."""
    return " ".join(text.split()).replace(f"<{TAG}", f"&lt;{TAG}").replace(f"</{TAG}", f"&lt;/{TAG}")


def running_for(seconds: float | None) -> str:
    """How long a command has run, as `1h48m`, `12m` or `40s` (`?` when it is not known)."""
    if seconds is None:
        return "?"
    whole = int(seconds)
    hours, minutes = whole // 3600, whole % 3600 // 60
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m" if minutes else f"{whole}s"


def held_envelope(reason: str, context_pct: int | None, line_pct: float | None, shells: list[ToolShell]) -> str:
    """The notice for a conversation held back for `reason` at `context_pct` against the line `line_pct`, while its
    tools run `shells`."""
    line = "?" if line_pct is None else f"{line_pct:g}"
    commands = "\n".join(f"- pid {shell.pid}, running {running_for(shell.elapsed_seconds)}: {_plain(shell.command)}"
                         for shell in shells)
    return (f'{OPENING}\n<{TAG} reason="{reason}" context_pct="{context_pct}" line="{line}">\n'
            f"{_INTRO}\n{commands}\n{_OUTRO}\n"
            f"</{TAG}>")
