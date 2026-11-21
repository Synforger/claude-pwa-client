"""`tabs new`'s words and the `<child-start>` block it writes (`backend/cli/child_start.py`)."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.cli.child_start import NewChild, child_start_text, parse_new, read_settings, settings_lines


def test_without_options_the_block_names_the_tier_only():
    assert parse_new(["t", "task.md"]) == NewChild("t", Path("task.md"), {})
    assert child_start_text("projects/AP", {}, "do it") == "<child-start>\ntier=projects/AP\n</child-start>\n\ndo it"


def test_the_model_and_the_effort_follow_the_tier_in_a_fixed_order():
    asked = parse_new(["t", "task.md", "--effort", "low", "--model", "haiku"])
    assert asked == NewChild("t", Path("task.md"), {"effort": "low", "model": "haiku"})
    assert child_start_text("normal", asked.settings, "x") == (
        "<child-start>\ntier=normal\nmodel=haiku\neffort=low\n</child-start>\n\nx")


def test_one_option_alone_writes_its_line_alone():
    asked = parse_new(["t", "task.md", "--model", "claude-sonnet-5-5"])
    assert child_start_text("normal", asked.settings, "x").splitlines()[1:3] == ["tier=normal", "model=claude-sonnet-5-5"]


@pytest.mark.parametrize("words", [["t"], ["t", "f", "--model"], ["t", "f", "--model", "a", "--model", "b"],
                                   ["t", "f", "--temperature", "1"], ["t", "f", "extra"]])
def test_other_words_are_not_the_form(words):
    assert parse_new(words) is None


@pytest.mark.parametrize("value", ["haiku\ntier=normal", "a b", "</child-start>", "-x", ""])
def test_a_value_that_could_break_the_block_is_refused(value):
    refused = parse_new(["t", "f", "--effort", value])
    assert isinstance(refused, str) and "--effort" in refused


def test_the_settings_written_into_the_block_are_read_back_as_they_were_chosen():
    for settings in ({}, {"model": "haiku"}, {"effort": "low"}, {"model": "opus", "effort": "xhigh"}):
        assert read_settings(child_start_text("projects/AP", settings, "do it\nmodel=opus")) == settings


@pytest.mark.parametrize("text", [
    "do it",                                                        # no block
    "please read this:\n<child-start>\nmodel=opus\n</child-start>",  # a block that is not at the head
])
def test_a_text_that_does_not_start_with_the_block_carries_no_settings(text):
    assert read_settings(text) == {}


def test_only_the_chosen_keys_with_one_word_values_are_read():
    text = "<child-start>\ntier=normal\nmodel=a b\neffort=low\ncolour=red\n</child-start>\n\nx"
    assert read_settings(text) == {"effort": "low"}


def test_a_stored_value_that_is_not_one_word_is_never_written_as_a_line():
    assert settings_lines({"effort": "high", "model": "haiku\ntier=normal"}) == ["effort=high"]
    assert settings_lines({"model": "haiku", "effort": "low", "colour": "red"}) == ["model=haiku", "effort=low"]
