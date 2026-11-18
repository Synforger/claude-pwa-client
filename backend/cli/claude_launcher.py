"""A launcher for an agent with no launch script of its own: it takes the client's two launch words and starts `claude`
with every other argument it was given. `bin/claude-launcher` runs it.

With `"launcher": true`, the client types `<launch_alias> --first-message-file <file>` to start a new conversation and
`<launch_alias> --resume <id>` to reopen one (`docs/reference/config.md`). A plain `claude …` alias cannot take the
first, and the client reopens such a tab with a bare `claude --resume <id>`, which drops the alias's arguments
(`--model`, `--tools`, …). Written as the alias, this launcher keeps them on every start.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import NamedTuple

CLAUDE = os.environ.get("CLAUDE_LAUNCHER_CLAUDE", "claude")
FIRST_MESSAGE_OPTION = "--first-message-file"
RESUME_OPTION = "--resume"


class LaunchWords(NamedTuple):
    arguments: list[str]
    first_message_file: Path | None
    resume_id: str | None


def parse(argv: list[str]) -> LaunchWords:
    """Split the client's launch words from the arguments meant for `claude`."""
    arguments: list[str] = []
    first_message_file: Path | None = None
    resume_id: str | None = None
    rest = list(argv)
    while rest:
        word = rest.pop(0)
        if word == FIRST_MESSAGE_OPTION and rest:
            first_message_file = Path(rest.pop(0))
        elif word == RESUME_OPTION and rest:
            resume_id = rest.pop(0)
        else:
            arguments.append(word)
    return LaunchWords(arguments, first_message_file, resume_id)


def command(words: LaunchWords, first_message: str | None) -> list[str]:
    """The `claude` command line for these words and the first message read from its file."""
    line = [CLAUDE, *words.arguments]
    if words.resume_id is not None:
        line += [RESUME_OPTION, words.resume_id]
    if first_message:
        # a message that starts with a dash would be read as an option
        line.append(" " + first_message if first_message.startswith("-") else first_message)
    return line


def main(argv: list[str]) -> int:
    words = parse(argv)
    first_message = None
    if words.first_message_file is not None:
        # the client writes the message where only this user can read it, and leaves the removal to the launcher
        try:
            first_message = words.first_message_file.read_text(encoding="utf-8")
        except OSError as error:
            print(f"claude-launcher: {words.first_message_file} を読めません: {error}", file=sys.stderr)
            return 1
        words.first_message_file.unlink(missing_ok=True)
    line = command(words, first_message)
    os.execvp(line[0], line)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
