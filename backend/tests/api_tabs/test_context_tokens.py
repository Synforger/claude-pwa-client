"""The context amount of an API tab: the three input counts of the last answer that carries a `usage`
(`backend/api_tabs/context_tokens.py` and `api_tab_record.last_context_tokens`)."""
from __future__ import annotations

import pytest

from backend.api_tabs.api_tab_record import last_context_tokens
from backend.api_tabs.context_tokens import context_tokens_of_row
from backend.tests.api_tabs.samples import append, assistant_row, tool_use_row, user_row


def test_the_amount_is_the_sum_of_the_three_input_counts():
    row = assistant_row("a1", "m1", "hi", usage={"input_tokens": 10, "cache_read_input_tokens": 200,
                                                  "cache_creation_input_tokens": 3000, "output_tokens": 99999})
    assert context_tokens_of_row(row) == 3210              # the output count is not part of what the next call carries


def test_a_missing_count_is_zero_and_a_row_without_usage_says_nothing():
    assert context_tokens_of_row(assistant_row("a1", "m1", "hi", usage={"input_tokens": 7})) == 7
    assert context_tokens_of_row(assistant_row("a1", "m1", "hi", usage={})) == 0
    assert context_tokens_of_row(assistant_row("a1", "m1", "hi")) is None
    assert context_tokens_of_row(user_row("u1", "hi")) is None
    assert context_tokens_of_row("not a row") is None


@pytest.mark.parametrize("bad", [True, -1, "5", 1.5, None])
def test_a_count_that_is_not_a_whole_number_is_zero(bad):
    assert context_tokens_of_row(assistant_row("a1", "m1", "hi", usage={"input_tokens": 4, "cache_read_input_tokens": bad})) == 4


def test_a_record_with_no_answer_has_no_amount_and_one_with_answers_takes_the_last(tmp_path):
    record = tmp_path / "r.jsonl"
    assert last_context_tokens(_empty(record)) is None
    append(record, user_row("u1", "hello"))
    assert last_context_tokens(record) is None             # no assistant row yet: no amount, not zero
    append(record, assistant_row("a1", "m1", "one", usage={"input_tokens": 100}), user_row("u2", "more"),
           assistant_row("a2", "m2", "two", usage={"input_tokens": 5, "cache_read_input_tokens": 400}),
           tool_use_row("a3", "m3", "t1"))                  # an answer with no usage after the last one that has it
    assert last_context_tokens(record) == 405


def test_an_answer_still_being_written_is_not_read(tmp_path):
    record = tmp_path / "r.jsonl"
    append(record, assistant_row("a1", "m1", "one", usage={"input_tokens": 100}),
           partial='{"type": "assistant", "message": {"usage": {"input_tokens": 999')
    assert last_context_tokens(record) == 100


def _empty(path):
    path.write_text("")
    return path
