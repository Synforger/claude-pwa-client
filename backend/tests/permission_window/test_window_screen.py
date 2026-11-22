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


def test_another_command_is_not_shown():
    assert not shows_command(read_screen(screens.approval("ls -la")), "rm -rf /")


def test_a_command_cut_short_on_the_screen_is_not_shown_whole():
    command = "echo hello world && cat /etc/hosts"
    assert not shows_command(read_screen(screens.cut_short(command)), command)


def test_the_hooks_input_that_only_starts_like_the_screen_is_not_shown():
    """A hook input made of what the screen shows and a harmless-looking end is not what the dialog shows."""
    assert not shows_command(read_screen(screens.cut_short("echo hello world && ls")), "echo hello w && rm x")


def test_a_dialog_with_no_rule_above_it_is_not_read():
    no_rule = screens.approval("ls -la").replace(screens.RULE, "")
    assert not shows_command(read_screen(no_rule), "ls -la")


def test_text_above_the_dialog_is_not_the_dialog():
    """The command printed earlier in the conversation does not stand for the one the dialog shows."""
    shown_before = "● earlier: ls -la\n" + screens.approval("ls").replace("ls\n", "ls\n", 1)
    assert not shows_command(read_screen(shown_before), "ls -la")
