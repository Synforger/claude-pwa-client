"""Screens of Claude Code as the pane shows them, for the tests of the permission window: the window of an approval (as
measured in a real tab: the dialog under a rule, the guard's reason, `1. Yes` / `2. No`, `Esc to cancel · Tab to amend`),
two windows in a row, a question, the input box alone, a reply with `1. Yes` / `2. No` in it, a picker, a window that
offers three choices and one that cuts the command short."""
from __future__ import annotations

RULE = "─" * 40
INPUT_BOX = f"{RULE}\n ❯ \n{RULE}\n  ? for shortcuts"
FOOTER = " Esc to cancel · Tab to amend"


def approval(command: str = "ls -la", reason: str = "guard says so", *, position: str = "") -> str:
    """The window of an approval of a Bash command (`position` is the `1 of 2` of a second window)."""
    head = f" Bash command{position}"
    return (f"● Running the command\n\n{RULE}\n{head}\n\n   {command}\n   List the files\n\n"
            f" Hook PreToolUse:Bash requires confirmation for this command: {reason} [settings]\n\n"
            f" Do you want to proceed?\n ❯ 1. Yes\n   2. No\n\n{FOOTER}")


def three_choices(command: str = "ls -la") -> str:
    return approval(command).replace("   2. No", "   2. Yes, and don't ask again for ls commands\n   3. No")


def cut_short(command: str) -> str:
    """The window of a command the dialog shows only the start of."""
    return approval(command[:12] + " … (ctrl+o to expand)")


def question() -> str:
    return (f"● Asking\n\n{RULE}\n Which one?\n\n ❯ 1. Option A\n   2. Option B\n   3. Type something\n\n"
            " Enter to select · ↑/↓ to navigate · Esc to cancel")


def picker() -> str:
    return f"{RULE}\n Select model\n\n ❯ 1. Default\n   2. Opus\n\n Enter to confirm · Esc to exit"


def idle(text: str = "● done") -> str:
    return f"{text}\n\n{INPUT_BOX}"


def numbers_in_a_reply() -> str:
    """A reply that has `1. Yes` and `2. No` in it, above the input box: not a window."""
    return idle("● Choose one:\n  1. Yes\n  2. No\n  ❯ 1. Yes   (a quoted line)")
