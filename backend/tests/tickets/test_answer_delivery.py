"""Delivering the operator's answers: when one is typed (idle tab, the stop of a turn, the patrol), when it waits, what a
refused delivery leaves of it, and that three triggers at once type it once."""
from __future__ import annotations

import asyncio

import pytest

from backend.jsonl.jsonl_predicates import CLIENT_NOTICE_OPENING
from backend.tests.async_run import run
from backend.tests.tickets.samples import answered_ticket, delivery_env, queued, refusal  # noqa: F401
from backend.tests.tickets.samples import ticket_env  # noqa: F401
from backend.tickets import answer_delivery, answer_queue, ticket_file, ticket_index, ticket_service
from backend.tickets.answer_queue import AnswerKey


def _delivered_lines(env, ticket: str) -> list[dict]:
    return [entry for entry in ticket_file.read(env.tickets, ticket) if entry["kind"] == "delivered"]


def test_an_idle_holder_is_typed_the_answer_in_the_clients_envelope_and_the_queue_empties(delivery_env):
    key = answered_ticket(delivery_env, text="Take B")
    run(answer_delivery.deliver(key))
    [(tab, message)] = delivery_env.typed
    assert tab == "ses_a" and queued() == []
    assert message == (f"{CLIENT_NOTICE_OPENING}\n<ticket-answer ticket=\"{key.ticket}\">\n<operator-said>\nTake B\n</operator-said>\n"
                       f"票 {key.ticket} への操作者の答えです。 全体は `tabs ticket show {key.ticket}`\n</ticket-answer>")
    [line] = _delivered_lines(delivery_env, key.ticket)
    assert (line["asked_at"], line["result"], line["to"], line["tab"]) == (key.asked_at, "typed", "ses_a", "")


def test_a_child_that_holds_the_ticket_holds_work_again_once_the_answer_is_typed(delivery_env):
    delivery_env.tabs["ses_a"].parent_id = "ses_b"
    key = answered_ticket(delivery_env)
    run(answer_delivery.deliver(key))
    assert delivery_env.handed == [("ses_b", "ses_a")]


def test_a_holder_that_is_no_child_has_no_memo_set_back(delivery_env):
    run(answer_delivery.deliver(answered_ticket(delivery_env)))
    assert delivery_env.handed == []


def test_a_working_holder_is_not_typed_to_and_the_stop_of_its_turn_types_the_answer(delivery_env):
    key = answered_ticket(delivery_env)
    delivery_env.busy.add("ses_a")
    run(answer_delivery.deliver(key))
    run(answer_delivery.on_stop("ses_a"))
    assert delivery_env.typed == [] and queued() == [key]
    delivery_env.busy.discard("ses_a")
    run(answer_delivery.on_stop("ses_b"))                       # the stop of another tab is not this answer's trigger
    assert delivery_env.typed == []
    run(answer_delivery.on_stop("ses_a"))
    assert [tab for tab, _ in delivery_env.typed] == ["ses_a"] and queued() == []


def test_a_holder_asked_to_close_is_not_typed_to(delivery_env):
    key = answered_ticket(delivery_env)
    delivery_env.close_asked.add("ses_a")
    run(answer_delivery.deliver(key))
    assert delivery_env.typed == [] and queued() == [key]
    delivery_env.close_asked.clear()                             # the conversation after the rollover is not asked
    run(answer_delivery.patrol_once())
    assert len(delivery_env.typed) == 1 and queued() == []


def test_the_patrol_types_an_answer_that_waited(delivery_env):
    key = answered_ticket(delivery_env)
    delivery_env.busy.add("ses_a")
    run(answer_delivery.patrol_once())
    assert delivery_env.typed == []
    delivery_env.busy.clear()
    run(answer_delivery.patrol_once())
    assert len(delivery_env.typed) == 1 and queued() == []
    assert key not in queued()


def test_a_holder_the_account_hold_stopped_has_the_answer_kept(delivery_env):
    key = answered_ticket(delivery_env)
    delivery_env.kept.add("ses_a")
    run(answer_delivery.deliver(key))
    assert queued() == [] and _delivered_lines(delivery_env, key.ticket)[0]["result"] == "kept"


@pytest.mark.parametrize("code", ["agent_message_unconfirmed", "agent_message_not_taken"])
def test_an_answer_that_may_have_arrived_is_not_typed_again(delivery_env, code):
    key = answered_ticket(delivery_env)
    delivery_env.fail["ses_a"] = refusal(500, code)
    run(answer_delivery.deliver(key))
    delivery_env.fail.clear()
    run(answer_delivery.patrol_once())
    assert delivery_env.typed == [] and queued() == []
    assert [line["result"] for line in _delivered_lines(delivery_env, key.ticket)] == ["unconfirmed"]


@pytest.mark.parametrize("code", ["agent_message_receiver_not_ready", "agent_message_not_sent"])
def test_an_answer_refused_before_typing_waits_5_seconds_then_double_and_stops_at_5_minutes(delivery_env, code):
    key = answered_ticket(delivery_env)
    delivery_env.fail["ses_a"] = refusal(409, code)
    tries = []
    for _ in range(9):
        before = len(delivery_env.typed)
        run(answer_delivery.patrol_once())                      # the patrol leaves it while its wait is not over
        tries.append(answer_delivery._retry_after[key][1])
        run(answer_delivery.patrol_once())
        delivery_env.clock[0] = answer_delivery._retry_after[key][0]
        assert len(delivery_env.typed) == before and queued() == [key]
    assert tries[:1] == [5.0] and sorted(set(tries)) == [5.0, 10.0, 20.0, 40.0, 80.0, 160.0, 300.0]
    delivery_env.fail.clear()
    run(answer_delivery.patrol_once())
    assert len(delivery_env.typed) == 1 and queued() == []


def test_a_news_trigger_does_not_wait_for_the_retry_wait(delivery_env):
    key = answered_ticket(delivery_env)
    delivery_env.fail["ses_a"] = refusal(409, "agent_message_receiver_not_ready")
    run(answer_delivery.deliver(key))
    delivery_env.fail.clear()
    run(answer_delivery.on_stop("ses_a"))
    assert len(delivery_env.typed) == 1 and queued() == []


def test_a_holder_that_cannot_be_reached_is_not_typed_to_and_is_tried_again_after_a_wait(delivery_env):
    key = answered_ticket(delivery_env)
    delivery_env.unreachable.add("ses_a")
    run(answer_delivery.patrol_once())
    assert delivery_env.typed == [] and queued() == [key] and answer_delivery._retry_after[key][1] == 5.0
    delivery_env.unreachable.clear()
    run(answer_delivery.patrol_once())                           # its wait is not over
    assert delivery_env.typed == []
    delivery_env.clock[0] += 5
    run(answer_delivery.patrol_once())
    assert len(delivery_env.typed) == 1


@pytest.mark.parametrize("failure", [refusal(503, "ticket_check_failed"), refusal(409, "ticket_place_unknown")])
def test_a_guard_that_does_not_run_or_a_place_that_is_not_found_keeps_the_answer_for_another_try(delivery_env, monkeypatch, failure):
    key = answered_ticket(delivery_env)

    async def fail(*args):
        raise failure

    monkeypatch.setattr(answer_delivery.ticket_checks, "check_covers", fail)
    run(answer_delivery.deliver(key))
    assert delivery_env.typed == [] and queued() == [key] and _delivered_lines(delivery_env, key.ticket) == []


def test_a_holder_that_has_not_read_the_boundary_is_not_given_the_answer(delivery_env, caplog):
    key = answered_ticket(delivery_env)
    delivery_env.guard.use("covers", covers={"refuse_sessions": ["conv-ses_a"]})
    with caplog.at_level("WARNING"):
        run(answer_delivery.deliver(key))
    assert delivery_env.typed == [] and queued() == []
    assert _delivered_lines(delivery_env, key.ticket)[0]["result"] == "refused"
    assert any("result=refused" in record.message for record in caplog.records)


def test_the_guard_is_asked_only_whether_the_holder_has_read_the_boundary_never_about_the_words(delivery_env):
    key = answered_ticket(delivery_env)
    delivery_env.guard.use("covers", "write", "read")
    run(answer_delivery.deliver(key))
    assert [call["mode"] for call in delivery_env.guard.calls()] == ["covers"] and len(delivery_env.typed) == 1


def test_an_answer_to_a_ticket_that_closed_is_typed_with_a_line_saying_so(delivery_env):
    key = answered_ticket(delivery_env)
    run(ticket_service.close("ses_b", key.ticket, "done meanwhile"))
    run(answer_delivery.deliver(key))
    [(_tab, message)] = delivery_env.typed
    assert "Take B" in message and message.endswith("。 票は閉じています\n</ticket-answer>")
    assert queued() == [] and _delivered_lines(delivery_env, key.ticket)[0]["result"] == "typed"


def test_a_holder_that_was_closed_gives_the_ticket_back_and_the_answer_goes_to_the_tab_that_asked_first(delivery_env):
    key = answered_ticket(delivery_env, holder="ses_b")
    del delivery_env.tabs["ses_b"]
    run(answer_delivery.deliver(key))
    assert [tab for tab, _ in delivery_env.typed] == ["ses_a", "ses_a"]          # the notice of the return, then the answer
    assert "あなたに戻りました" in delivery_env.typed[0][1] and "Take B" in delivery_env.typed[1][1]
    assert ticket_index.get(key.ticket).holder == "ses_a" and queued() == []


def test_when_no_tab_is_left_the_answer_waits_and_nothing_is_typed(delivery_env):
    key = answered_ticket(delivery_env, holder="ses_b")
    del delivery_env.tabs["ses_b"], delivery_env.tabs["ses_a"]
    run(answer_delivery.deliver(key))
    assert delivery_env.typed == [] and queued() == [key] and ticket_index.get(key.ticket).holder == ""


def test_a_ticket_that_closed_with_its_holder_gone_leaves_nobody_to_tell(delivery_env, caplog):
    key = answered_ticket(delivery_env, holder="ses_b")
    run(ticket_service.close("ses_a", key.ticket, ""))
    del delivery_env.tabs["ses_b"]
    with caplog.at_level("WARNING"):
        run(answer_delivery.deliver(key))
    assert delivery_env.typed == [] and queued() == []
    assert _delivered_lines(delivery_env, key.ticket)[0]["result"] == "refused"


def test_an_answer_whose_ticket_is_not_in_the_index_is_let_go(delivery_env, caplog):
    key = answered_ticket(delivery_env)
    (delivery_env.tickets / "index.json").write_text("{}")
    with caplog.at_level("WARNING"):
        run(answer_delivery.deliver(key))
    assert delivery_env.typed == [] and queued() == [] and any("no row in the index" in r.message for r in caplog.records)


def test_a_holder_on_another_machine_is_not_typed_to_from_here(delivery_env):
    key = answered_ticket(delivery_env)
    ticket_index.put(key.ticket, ticket_index.get(key.ticket)._replace(holder="office:ses_x"))
    run(answer_delivery.deliver(key))
    assert delivery_env.typed == [] and queued() == [key]


def test_an_answer_that_was_delivered_already_is_not_typed_again(delivery_env):
    key = answered_ticket(delivery_env)
    run(answer_delivery.deliver(key))
    answer_queue.add(key)                                        # a queue that still held it after a crash
    run(answer_delivery.deliver(key))
    assert len(delivery_env.typed) == 1 and queued() == []


def test_three_triggers_at_the_same_time_type_the_answer_once(delivery_env):
    key = answered_ticket(delivery_env)

    async def together():
        await asyncio.gather(answer_delivery.deliver(key), answer_delivery.deliver(key, from_patrol=True),
                             answer_delivery.on_stop("ses_a"))

    run(together())
    assert len(delivery_env.typed) == 1 and len(_delivered_lines(delivery_env, key.ticket)) == 1


def test_an_unforeseen_error_keeps_the_answer_and_tries_it_again_after_a_wait(delivery_env):
    key = answered_ticket(delivery_env)
    delivery_env.fail["ses_a"] = RuntimeError("boom")
    run(answer_delivery.deliver(key))
    assert queued() == [key] and answer_delivery._retry_after[key][1] == 5.0
    delivery_env.fail.clear()
    delivery_env.clock[0] += 5
    run(answer_delivery.patrol_once())
    assert len(delivery_env.typed) == 1 and queued() == []


def test_a_restart_queues_again_the_answers_that_were_written_and_never_delivered(delivery_env):
    key = answered_ticket(delivery_env, text="One")
    second = answered_ticket(delivery_env, text="Two")
    run(answer_delivery.deliver(second))                         # delivered: its `delivered` line is in the file
    answer_queue.remove(key)                                     # the queue lost the first (= a crash after the file)
    assert run(answer_delivery.restore_queue()) is True
    assert queued() == [key]
    assert run(answer_delivery.restore_queue()) is True and queued() == [key]       # never twice


def test_the_restore_says_it_is_not_complete_when_a_place_cannot_be_found(delivery_env):
    answered_ticket(delivery_env)
    ticket_index.put("home-261119-99", ticket_index.IndexRow("0" * 16, "ses_a", "ses_a", "open", None))
    assert run(answer_delivery.restore_queue()) is False


def test_an_answer_queued_in_the_quiet_time_after_the_start_is_left_to_the_patrol(delivery_env, monkeypatch):
    monkeypatch.undo()                                           # the real `start_delivery`, with the real clock
    started = []

    async def deliver(key, **kwargs):
        started.append(key)

    async def scenario():
        monkeypatch.setattr(answer_delivery, "deliver", deliver)
        key = AnswerKey("home-261119-01", "x")
        monkeypatch.setattr(answer_delivery, "_quiet_until", answer_delivery.time.monotonic() + 30)
        answer_delivery.start_delivery(key)
        await asyncio.sleep(0)
        assert started == []
        monkeypatch.setattr(answer_delivery, "_quiet_until", 0.0)
        answer_delivery.start_delivery(key)
        await asyncio.sleep(0)
        assert started == [key]

    run(scenario())


def test_a_place_that_cannot_be_found_while_giving_the_ticket_back_leaves_the_answer_waiting(delivery_env, monkeypatch):
    key = answered_ticket(delivery_env, holder="ses_b")
    del delivery_env.tabs["ses_b"]

    async def not_found(place_key):
        raise refusal(409, "ticket_place_unknown")

    monkeypatch.setattr(answer_delivery.ticket_return.ticket_places, "folder_for", not_found)
    run(answer_delivery.deliver(key))
    assert delivery_env.typed == [] and queued() == [key] and ticket_index.get(key.ticket).holder == "ses_b"
