"""Which API error rows the client carries a tab on after (`jsonl_predicates.is_continuable_error_row`), and how the
record's fold keeps the stop and the streak (`sleep/record_facts.py`)."""
from __future__ import annotations

import pytest

from backend.fork.fork import is_limit_stop_row
from backend.jsonl.jsonl_predicates import is_api_error_resume, is_continuable_error_row
from backend.sleep.record_facts import RecordFacts, fold_row
from backend.tests.error_resume.samples import CUT_WORDS, error_row, hidden, prompt, resume_prompt, said


def _fold(*rows: dict) -> RecordFacts:
    facts = RecordFacts()
    for row in rows:
        fold_row(facts, row)
    return facts


@pytest.mark.parametrize("api_error", [None, "connection_failed", "computer_slept", "stream_idle_timeout",
                                       "a_cause_claude_code_adds_later"])
def test_a_server_error_from_the_network_or_the_api_is_carried_on(api_error):
    assert is_continuable_error_row(error_row(api_error=api_error))


@pytest.mark.parametrize("api_error", ["tls_untrusted_ca", "tls_cert_signature_failure", "gateway_content_type"])
def test_a_server_error_from_the_setup_of_the_network_is_not(api_error):
    assert not is_continuable_error_row(error_row(api_error=api_error))


def test_a_passing_429_is_carried_on_and_a_usage_limit_is_not():
    passing = error_row(error="rate_limit", transient=True)
    limit = error_row(error="rate_limit")
    assert is_continuable_error_row(passing) and not is_limit_stop_row(passing)
    assert not is_continuable_error_row(limit) and is_limit_stop_row(limit)


@pytest.mark.parametrize("error", ["invalid_request", "authentication_failed", "model_not_found", "max_output_tokens",
                                   "unknown"])
def test_an_error_that_a_message_meets_again_is_not_carried_on(error):
    assert not is_continuable_error_row(error_row(error=error))


def test_rows_that_are_not_api_errors_of_the_conversation_are_not():
    row = error_row()
    del row["isApiErrorMessage"]
    assert not is_continuable_error_row(row)
    assert not is_continuable_error_row(error_row(sidechain=True))
    assert not is_continuable_error_row({**error_row(), "type": "user"})


def test_the_clients_message_is_told_from_other_prompts_also_when_pasted():
    text = resume_prompt()["message"]["content"]
    assert is_api_error_resume(text)
    assert is_api_error_resume(f'<pasted_content id="7">\n{text}\n</pasted_content id="7">')
    assert not is_api_error_resume("please mention <api-error-resume in your answer")


def test_a_turn_that_ends_in_the_error_leaves_its_stop():
    facts = _fold(prompt(), said(), error_row(at=100.0, api_error="connection_failed"))
    stop = facts.error_stop
    assert stop is not None and stop.uuid == "err1" and stop.at == 100.0
    assert (stop.error, stop.cause, stop.words) == ("server_error", "connection_failed", CUT_WORDS)
    assert facts.error_streak == 0 and not facts.awaiting_tool_result and facts.limit_stop is None


def test_the_cause_falls_back_to_how_the_stream_was_cut():
    assert _fold(error_row(cut="network_down")).error_stop.cause == "network_down"


@pytest.mark.parametrize("after", [
    prompt("I am here"), said(), hidden(), prompt("[Request interrupted by user]"),
    {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]}},
    {"type": "attachment", "attachment": {"type": "queued_command", "commandMode": "prompt",
                                          "origin": {"kind": "human"}, "prompt": "later"}},
    error_row(error="invalid_request"),
])
def test_any_row_of_the_conversation_after_the_error_ends_the_stop(after):
    assert _fold(prompt(), error_row(), after).error_stop is None


def test_rows_of_a_sub_agent_and_other_kinds_change_nothing():
    facts = _fold(prompt(), error_row(), error_row("sub", sidechain=True), {"type": "system", "content": "note"},
                  {"type": "attachment", "attachment": {"type": "file"}})
    assert facts.error_stop is not None and facts.error_stop.uuid == "err1"


def test_the_streak_counts_the_clients_messages_that_met_the_error_again():
    rows = [prompt(), error_row("e0")]
    assert _fold(*rows).error_streak == 0
    for count in (1, 2, 3):
        rows += [resume_prompt(), error_row(f"e{count}")]
        assert _fold(*rows).error_streak == count


def test_a_reply_cut_mid_way_still_counts_although_it_wrote_its_first_part():
    facts = _fold(prompt(), error_row("e0"), resume_prompt(), said("half of it"), error_row("e1"))
    assert facts.error_streak == 1


def test_claude_codes_own_retries_in_one_turn_count_once():
    facts = _fold(prompt(), error_row("e0"), resume_prompt(), error_row("e1"), hidden(), said(), error_row("e2"))
    assert facts.error_streak == 1 and facts.error_stop.uuid == "e2"


def test_a_prompt_of_anyone_else_sets_the_streak_back():
    rows = [prompt(), error_row("e0"), resume_prompt(), error_row("e1")]
    assert _fold(*rows, prompt("me"), error_row("e2")).error_streak == 0
    queued = {"type": "attachment", "attachment": {"type": "queued_command", "commandMode": "prompt",
                                                   "origin": {"kind": "human"}, "prompt": "me"}}
    assert _fold(*rows, queued, error_row("e2")).error_streak == 0


def test_a_background_notification_between_keeps_the_streak():
    rows = [prompt(), error_row("e0"), resume_prompt(), error_row("e1"),
            prompt("<task-notification>done</task-notification>", origin="task-notification"), error_row("e2")]
    facts = _fold(*rows)
    assert facts.error_streak == 1 and facts.error_stop.uuid == "e2"


def test_the_clients_message_typed_while_claude_worked_opens_its_turn():
    queued = {"type": "attachment", "attachment": {"type": "queued_command", "commandMode": "prompt",
                                                   "origin": {"kind": "human"},
                                                   "prompt": resume_prompt()["message"]["content"]}}
    assert _fold(prompt(), error_row("e0"), queued, error_row("e1")).error_streak == 1
