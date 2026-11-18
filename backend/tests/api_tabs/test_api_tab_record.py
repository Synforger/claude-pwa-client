"""Reading an API tab's record: the segment the replay reads and what one look at the file finds
(`backend/api_tabs/api_tab_record.py`)."""
from __future__ import annotations

from backend.api_tabs import record_segments
from backend.api_tabs.api_tab_record import end_of_complete_lines, line_number_at, look_at_record
from backend.jsonl.chain import Segment
from backend.tests.api_tabs.samples import TAB_ID, append, assistant_row, user_row


def test_the_replay_reads_the_one_record_from_position_zero(api_env):
    assert record_segments(TAB_ID) == []                       # the file is not there yet: an empty conversation
    append(api_env.record, user_row("u1", "hello"))
    assert record_segments(TAB_ID) == [Segment(api_env.record, 0)]


def test_a_tab_that_is_not_an_api_tab_has_no_segments_of_this_kind(api_env):
    assert record_segments("ses_abc") is None                  # the caller reads a Claude tab's chain instead


def test_the_end_of_whole_rows_stops_before_a_row_being_written(tmp_path):
    record = tmp_path / "r.jsonl"
    record.write_text("")
    assert end_of_complete_lines(record) == 0
    append(record, user_row("u1", "hello"))
    whole = record.stat().st_size
    append(record, partial='{"type": "user", "mess')
    assert end_of_complete_lines(record) == whole


def test_the_first_look_starts_from_the_end_so_a_restart_does_not_stream_the_record_again(api_env):
    append(api_env.record, user_row("u1", "hello"), assistant_row("a1", "m1", "hi", usage={"input_tokens": 12}))
    found = look_at_record(api_env.record, None, False)
    assert found.present and found.rows == [] and found.offset == api_env.record.stat().st_size
    assert found.scanned and found.scanned_tokens == 12


def test_a_record_that_is_not_there_yet_is_read_from_zero_once_it_appears(api_env):
    first = look_at_record(api_env.record, None, False)
    assert (first.present, first.offset, first.rows, first.rewound) == (False, 0, [], False)
    append(api_env.record, user_row("u1", "hello"))
    later = look_at_record(api_env.record, first.offset, first.present)
    assert [pos for _raw, pos in later.rows] == [api_env.record.stat().st_size] and later.present


def test_new_rows_are_read_and_a_row_being_written_waits(api_env):
    append(api_env.record, user_row("u1", "hello"))
    start = look_at_record(api_env.record, None, False)
    append(api_env.record, user_row("u2", "again"), partial='{"type": "user", "mess')
    found = look_at_record(api_env.record, start.offset, True)
    assert len(found.rows) == 1 and '"u2"' in found.rows[0][0]
    assert found.offset == end_of_complete_lines(api_env.record)          # the written-so-far part is not taken


def test_a_record_that_got_shorter_rewinds_and_a_vanished_one_too(api_env):
    append(api_env.record, user_row("u1", "hello"), assistant_row("a1", "m1", "hi", usage={"input_tokens": 12}))
    start = look_at_record(api_env.record, None, False)
    api_env.record.write_text("")
    append(api_env.record, user_row("u9", "fresh"))
    shorter = look_at_record(api_env.record, start.offset, True)
    assert shorter.rewound and len(shorter.rows) == 1 and shorter.scanned and shorter.scanned_tokens is None
    api_env.record.unlink()
    gone = look_at_record(api_env.record, shorter.offset, True)
    assert (gone.present, gone.offset, gone.rewound) == (False, 0, True)


def test_the_number_of_a_row_is_counted_from_the_file(api_env):
    append(api_env.record, user_row("u1", "one"), user_row("u2", "two"), user_row("u3", "three"))
    rows = look_at_record(api_env.record, 0, True).rows
    assert [line_number_at(api_env.record, pos) for _raw, pos in rows] == [1, 2, 3]
