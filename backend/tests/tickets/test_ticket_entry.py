"""The lines of a ticket: made, written, read back in time order, and what a reader that may not read one is shown."""
from __future__ import annotations

import json

from backend.tickets import ticket_entry
from backend.tickets.ticket_entry import Writer

WRITER = Writer("ses_a", "client work", "projects/AP")


def test_a_line_has_the_kind_the_time_the_writer_and_the_text():
    entry = ticket_entry.make_entry(ticket_entry.ADDED, WRITER, "done", at="2026-11-19T01:00:00.000+00:00")
    assert entry == {"kind": "added", "at": "2026-11-19T01:00:00.000+00:00", "tab": "ses_a", "tab_title": "client work",
                     "tier": "projects/AP", "text": "done"}


def test_the_fields_only_some_kinds_have_come_with_the_line():
    entry = ticket_entry.make_entry(ticket_entry.ASKED, WRITER, "which?", at="t", ask_kind="decide", recommend="A")
    assert (entry["ask_kind"], entry["recommend"]) == ("decide", "A")


def test_a_line_is_one_json_object_and_a_newline_with_japanese_kept_as_it_is():
    line = ticket_entry.to_line(ticket_entry.make_entry(ticket_entry.ADDED, WRITER, "日本語", at="t"))
    assert line.endswith("\n") and "\n" not in line[:-1] and "日本語" in line
    assert json.loads(line)["text"] == "日本語"


def test_the_lines_are_read_back_by_time_and_a_damaged_line_is_left_out():
    late = ticket_entry.make_entry(ticket_entry.ADDED, WRITER, "late", at="2026-11-19T02:00:00.000+00:00")
    early = ticket_entry.make_entry(ticket_entry.OPENED, WRITER, "early", at="2026-11-19T01:00:00.000+00:00")
    raw = ticket_entry.to_line(late) + "{not json\n" + "[1, 2]\n" + ticket_entry.to_line(early)
    assert [entry["text"] for entry in ticket_entry.parse_lines(raw)] == ["early", "late"]


def test_lines_of_the_same_time_keep_the_order_they_were_written_in():
    first = ticket_entry.make_entry(ticket_entry.OPENED, WRITER, "request", at="t")
    second = ticket_entry.make_entry(ticket_entry.OPERATOR, WRITER, "words", at="t")
    assert [e["text"] for e in ticket_entry.parse_lines(ticket_entry.to_line(first) + ticket_entry.to_line(second))] == [
        "request", "words"]


def test_the_title_is_judged_with_the_text_of_the_first_line():
    opened = ticket_entry.make_entry(ticket_entry.OPENED, WRITER, "body", at="t", title="the title")
    assert ticket_entry.judged_text(opened) == "the title\n\nbody"
    assert ticket_entry.judged_text(ticket_entry.make_entry(ticket_entry.ADDED, WRITER, "body", at="t")) == "body"


def test_a_line_that_may_not_be_read_is_replaced_by_one_with_nothing_of_it_but_its_kind_and_time():
    entry = ticket_entry.make_entry(ticket_entry.ADDED, WRITER, "secret", at="t1", title="t")
    assert ticket_entry.hidden(entry) == {"kind": "added", "at": "t1", "hidden": True,
                                          "text": ticket_entry.HIDDEN_TEXT}
