"""What the screen shows, as far as a window is concerned (`permission_window/window_screen.py`)."""
from __future__ import annotations

import pytest

from backend.permission_window.window_screen import ScreenKind, is_yes_no, read_screen, shows_command
from backend.tests.permission_window import screens


def test_the_window_of_an_approval_is_a_window_with_yes_and_no():
    reading = read_screen(screens.approval("ls -la"))
    assert reading.kind is ScreenKind.WINDOW
    assert reading.choices == (("1", "Yes"), ("2", "No")) and is_yes_no(reading)


def test_the_second_of_two_windows_is_a_window_too():
    assert read_screen(screens.approval("pwd", position=" (1 of 2)")).kind is ScreenKind.WINDOW


def test_a_question_and_a_picker_are_windows_that_are_not_yes_and_no():
    for screen in (screens.question(), screens.picker()):
        reading = read_screen(screen)
        assert reading.kind is ScreenKind.WINDOW and not is_yes_no(reading)


def test_the_input_box_alone_is_the_input_box():
    assert read_screen(screens.idle()).kind is ScreenKind.INPUT


def test_numbers_in_a_reply_are_not_a_window():
    """`1. Yes` and `2. No` in a reply, even with a marked line quoted, sit above the input box: the box is what the screen shows."""
    assert read_screen(screens.numbers_in_a_reply()).kind is ScreenKind.INPUT
    plain = "● Choose one:\n  1. Yes\n  2. No\n"
    assert read_screen(plain).kind is ScreenKind.OTHER


@pytest.mark.parametrize("screen", ["", "$ ls\nfile\n", "starting…"])
def test_a_screen_with_neither_is_other(screen):
    assert read_screen(screen).kind is ScreenKind.OTHER


def test_a_window_drawn_under_an_older_input_box_is_still_a_window():
    assert read_screen(screens.idle() + "\n" + screens.approval()).kind is ScreenKind.WINDOW


def test_the_input_box_drawn_under_an_older_window_is_the_input_box():
    assert read_screen(screens.approval() + "\n" + screens.idle()).kind is ScreenKind.INPUT


def test_three_choices_are_not_yes_and_no():
    assert not is_yes_no(read_screen(screens.three_choices()))


def test_the_fingerprint_changes_when_another_window_is_drawn():
    assert read_screen(screens.approval("ls")).fingerprint != read_screen(screens.approval("pwd")).fingerprint
    assert read_screen(screens.approval("ls")).fingerprint == read_screen(screens.approval("ls")).fingerprint


def test_the_command_is_shown_when_the_whole_of_it_is_on_the_screen():
    assert shows_command(read_screen(screens.approval("ls -la")), "ls -la")
    assert shows_command(read_screen(screens.approval("echo a &&\n  echo b")), "echo a && echo b")


def test_the_command_and_its_description_are_what_the_dialog_shows_when_the_call_has_one():
    reading = read_screen(screens.approval("ls -la", description="List the files"))
    assert shows_command(reading, "ls -la", "List the files")
    assert not shows_command(reading, "ls -la")                         # more on the screen than the hook's command
    assert not shows_command(read_screen(screens.approval("ls -la")), "ls -la", "List the files")


def test_g2_a_command_that_is_only_a_part_of_the_field_is_not_the_command():
    """Red before the fix: the command was looked for inside the dialog, so a head, a tail or a word of the reason passed."""
    assert not shows_command(read_screen(screens.approval("touch marker && ls -la")), "ls -la")
    assert not shows_command(read_screen(screens.approval("ls -la && touch marker")), "ls -la")
    assert not shows_command(read_screen(screens.approval("touch marker", "run ls -la first")), "ls -la")
    assert not shows_command(read_screen(screens.approval("rm -rf /")), "ls -la")


def test_a_command_cut_short_on_the_screen_is_not_shown_whole():
    command = "echo hello world && cat /etc/hosts"
    assert not shows_command(read_screen(screens.cut_short(command)), command)


def test_a_dialog_with_no_rule_above_it_is_not_read():
    no_rule = screens.approval("ls -la").replace(screens.RULE, "")
    assert read_screen(no_rule).command_field is None and not shows_command(read_screen(no_rule), "ls -la")


def test_g16_text_above_the_dialog_is_not_the_dialog():
    """The command printed earlier in the conversation, above the rule of the dialog, does not stand for the dialog's own."""
    earlier = "● earlier: ls -la\n   ls -la\n"
    reading = read_screen(earlier + screens.approval("touch marker"))
    assert reading.command_field == "touch marker" and not shows_command(reading, "ls -la")


def test_g16_the_usual_screens_of_a_tab_are_the_input_box():
    """The status line under the box, a title in the upper rule, what is typed in the box and a numbered line of a reply above
    it are the screen of a tab at rest."""
    for typed in ("", "hello", "1. fix the test", "1. Yes"):
        assert read_screen(screens.idle_with_typed(typed)).kind is ScreenKind.INPUT
        assert read_screen(screens.idle_with_typed(typed, title="tab name")).kind is ScreenKind.INPUT


def test_g1_what_is_typed_in_the_box_is_not_a_window_even_when_it_begins_with_a_number():
    """Red before the fix: `❯ 1. fix the test` in the box was read as the marked choice of a window."""
    for typed in ("1. fix the test", "1. Yes\n  2. No"):
        assert read_screen(screens.idle_with_typed(typed)).kind is ScreenKind.INPUT
    numbered = f"● done\n\n{screens.RULE}\n❯ 1. fix the test\n  2. push it\n{screens.RULE}\n  ? for shortcuts"
    assert read_screen(numbered).kind is ScreenKind.INPUT


def test_g6_a_titled_rule_frames_the_box_and_a_marked_line_above_it_is_not_a_window():
    """Red before the fix: the title took the rule for no rule, and the `❯ 1.` line that had scrolled up was the window."""
    titled = f"❯ 1. an earlier message\n\n● done\n\n{'─' * 24} tab name ──\n❯ \n{screens.RULE}\n  footer"
    assert read_screen(titled).kind is ScreenKind.INPUT


def test_a_box_with_a_selection_footer_under_it_is_a_window_not_the_box():
    framed = f"{screens.RULE}\n❯ 1. Yes\n  2. No\n{screens.RULE}\n Enter to confirm · Esc to exit"
    assert read_screen(framed).kind is ScreenKind.WINDOW


def test_g3_the_choices_are_the_run_the_marked_line_is_in_and_no_other_numbers_on_the_screen():
    """Red before the fix: the first line of each number on the whole screen was taken, so a list in an earlier reply was read
    as the window's."""
    earlier = "● earlier\n  1. Yes\n  2. No\n\n"
    always = screens.approval("ls -la").replace("❯ 1. Yes", "❯ 1. Yes, and always allow")
    assert not is_yes_no(read_screen(earlier + always))
    real = "● earlier\n  1. first\n  2. second\n\n" + screens.approval("ls -la")
    assert is_yes_no(read_screen(real)) and read_screen(real).choices == (("1", "Yes"), ("2", "No"))


def test_g3_a_choice_run_that_begins_above_the_marked_line_is_read_whole():
    assert read_screen(screens.question().replace(" ❯ 1. Option A\n   2. Option B", "   1. Option A\n ❯ 2. Option B")
                       ).choices == (("1", "Option A"), ("2", "Option B"), ("3", "Type something"))


def test_g4_a_label_is_read_whole():
    """Red before the fix: the label was cut at its first `(`, so `Yes (always allow)` was `Yes`."""
    for label in ("Yes (always allow)", "Yes, and always allow", "Yes, allow for this session"):
        window = screens.approval("ls -la").replace("❯ 1. Yes", f"❯ 1. {label}")
        assert read_screen(window).choices[0] == ("1", label) and not is_yes_no(read_screen(window))


def test_g5_a_window_drawn_with_a_border_on_its_sides_is_read_without_the_border():
    """Red before the fix: the border before the marked line hid it, and the screen was neither."""
    bordered = "\n".join(f"│{line:<60}│" if line and not line.startswith("─") else line
                         for line in screens.approval("ls -la").split("\n"))
    reading = read_screen(bordered)
    assert reading.kind is ScreenKind.WINDOW and is_yes_no(reading) and shows_command(reading, "ls -la")
