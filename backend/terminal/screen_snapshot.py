"""Turns the visible screen of a tmux pane into the bytes that paint it on a blank xterm.

Judgement only: nothing here touches tmux, a file or a socket, so the byte stream can be
tested from plain strings. `screen_capture` reads the pane and calls into this module;
`connect_snapshot` sends the result as the first output of a freshly attached terminal.

Why a snapshot exists: the control-mode client only receives the pane's output after it
attached, never the screen as it stands. Without a snapshot an attached terminal stays
black until the program in the pane happens to repaint.
"""
from __future__ import annotations

from dataclasses import dataclass

# CSI sequences used to paint the screen (see ECMA-48 / xterm control sequences)
_ESC = "\x1b"
SGR_RESET = f"{_ESC}[0m"
HIDE_CURSOR = f"{_ESC}[?25l"
SHOW_CURSOR = f"{_ESC}[?25h"
ENTER_ALTERNATE_SCREEN = f"{_ESC}[?1049h"
CLEAR_SCREEN = f"{_ESC}[H{_ESC}[2J"
ERASE_TO_LINE_END = f"{_ESC}[K"

# Fields of the one-line report that precedes the captured rows, in this order. Used as the
# `-F` format of `display-message`, so it must stay in step with `parse_screen_report`.
REPORT_FIELDS = (
    "cursor_x", "cursor_y", "cursor_flag", "alternate_on", "pane_width", "pane_height",
)
REPORT_FORMAT = " ".join("#{" + name + "}" for name in REPORT_FIELDS)


@dataclass(frozen=True)
class PaneScreen:
    """The visible screen of a pane at one instant (tmux's own coordinates, 0-based)."""

    lines: tuple[str, ...]
    cursor_x: int
    cursor_y: int
    is_cursor_visible: bool
    is_alternate: bool
    width: int
    height: int


def parse_screen_report(output: str) -> PaneScreen | None:
    """Parses `display-message` + `capture-pane -p -e` output taken in one tmux invocation.

    The first line is the report (`REPORT_FORMAT`), the rest are the screen rows. Returns
    None when the report is malformed, so the caller connects without a snapshot rather
    than painting a guess.
    """
    header, _, body = output.partition("\n")
    fields = header.split()
    if len(fields) != len(REPORT_FIELDS) or not all(f.isdigit() for f in fields):
        return None
    cursor_x, cursor_y, cursor_flag, alternate_on, width, height = (int(f) for f in fields)
    if width < 1 or height < 1:
        return None
    rows = body.split("\n")
    # capture-pane ends every row with a newline, so the split leaves one empty tail
    if rows and rows[-1] == "":
        rows.pop()
    rows = rows[:height] + [""] * (height - len(rows))
    return PaneScreen(
        lines=tuple(rows),
        cursor_x=cursor_x,
        cursor_y=cursor_y,
        is_cursor_visible=cursor_flag == 1,
        is_alternate=alternate_on == 1,
        width=width,
        height=height,
    )


def build_snapshot(screen: PaneScreen) -> bytes:
    """Builds the byte stream that paints `screen` on a blank terminal of the same size.

    The screen is cleared, every row is placed by its position (so a row that fills the
    width cannot shift the rows below it), and the cursor goes to tmux's cursor position.
    Attributes are reset after each row because a captured row may end with a colour still
    on, which would otherwise tint the erase and the next row.
    """
    parts = [SGR_RESET, HIDE_CURSOR]
    if screen.is_alternate:
        parts.append(ENTER_ALTERNATE_SCREEN)
    parts.append(CLEAR_SCREEN)
    for row, line in enumerate(screen.lines, start=1):
        parts.append(f"{_ESC}[{row};1H{line}{SGR_RESET}{ERASE_TO_LINE_END}")
    parts.append(f"{_ESC}[{screen.cursor_y + 1};{screen.cursor_x + 1}H")
    if screen.is_cursor_visible:
        parts.append(SHOW_CURSOR)
    return "".join(parts).encode("utf-8")
