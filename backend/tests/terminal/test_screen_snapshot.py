"""Unit tests for screen_snapshot: the bytes that paint a pane's screen, built from plain strings."""
from __future__ import annotations

from backend.terminal.screen_snapshot import PaneScreen, REPORT_FORMAT, build_snapshot, parse_screen_report

ESC = "\x1b"


def _screen(lines=("one", "two", "three"), *, cursor=(2, 1), visible=True, alternate=False, width=10) -> PaneScreen:
    return PaneScreen(
        lines=tuple(lines),
        cursor_x=cursor[0],
        cursor_y=cursor[1],
        is_cursor_visible=visible,
        is_alternate=alternate,
        width=width,
        height=len(lines),
    )


# --- parse_screen_report ---------------------------------------------------------------------------------------------

def test_report_format_names_the_fields_in_the_order_the_parser_reads_them():
    assert REPORT_FORMAT == "#{cursor_x} #{cursor_y} #{cursor_flag} #{alternate_on} #{pane_width} #{pane_height}"


def test_parse_reads_cursor_flags_size_and_rows():
    screen = parse_screen_report("6 5 1 0 40 3\nfirst\nsecond\n\n")
    assert screen == PaneScreen(
        lines=("first", "second", ""), cursor_x=6, cursor_y=5,
        is_cursor_visible=True, is_alternate=False, width=40, height=3,
    )


def test_parse_reads_a_hidden_cursor_and_the_alternate_screen():
    screen = parse_screen_report("2 2 0 1 30 2\na\nb\n")
    assert not screen.is_cursor_visible
    assert screen.is_alternate


def test_parse_pads_missing_rows_and_drops_extra_ones():
    assert parse_screen_report("0 0 1 0 5 3\nonly\n").lines == ("only", "", "")
    assert parse_screen_report("0 0 1 0 5 2\na\nb\nc\n").lines == ("a", "b")


def test_parse_keeps_escape_sequences_inside_rows():
    screen = parse_screen_report("0 0 1 0 5 1\n\x1b[31mred\x1b[39m\n")
    assert screen.lines == ("\x1b[31mred\x1b[39m",)


def test_parse_refuses_a_malformed_report():
    assert parse_screen_report("") is None
    assert parse_screen_report("not a report\nrow\n") is None
    assert parse_screen_report("1 2 3\nrow\n") is None
    assert parse_screen_report("0 0 1 0 0 0\n") is None  # a pane without cells


# --- build_snapshot --------------------------------------------------------------------------------------------------

def test_snapshot_starts_by_hiding_the_cursor_and_clearing_the_screen():
    text = build_snapshot(_screen()).decode()
    assert text.startswith(f"{ESC}[0m{ESC}[?25l{ESC}[H{ESC}[2J")


def test_snapshot_places_every_row_by_its_position():
    text = build_snapshot(_screen(("one", "two", "three"))).decode()
    for row, line in enumerate(("one", "two", "three"), start=1):
        assert f"{ESC}[{row};1H{line}{ESC}[0m{ESC}[K" in text
    assert text.index("one") < text.index("two") < text.index("three")


def test_snapshot_resets_attributes_before_erasing_so_a_colour_cannot_tint_the_erase():
    text = build_snapshot(_screen((f"{ESC}[44mblue",))).decode()
    assert f"{ESC}[44mblue{ESC}[0m{ESC}[K" in text


def test_snapshot_ends_with_the_cursor_at_tmux_position_and_shown():
    text = build_snapshot(_screen(cursor=(6, 4), visible=True)).decode()
    assert text.endswith(f"{ESC}[5;7H{ESC}[?25h")  # tmux counts from 0, the terminal from 1


def test_snapshot_leaves_a_hidden_cursor_hidden():
    text = build_snapshot(_screen(visible=False)).decode()
    assert text.endswith(f"{ESC}[2;3H")
    assert f"{ESC}[?25h" not in text


def test_snapshot_enters_the_alternate_screen_before_painting_it():
    text = build_snapshot(_screen(alternate=True)).decode()
    assert text.index(f"{ESC}[?1049h") < text.index(f"{ESC}[2J") < text.index("one")


def test_snapshot_stays_on_the_main_screen_otherwise():
    assert f"{ESC}[?1049h" not in build_snapshot(_screen(alternate=False)).decode()


def test_snapshot_encodes_wide_characters_as_utf8():
    assert "日本語".encode("utf-8") in build_snapshot(_screen(("日本語",)))
