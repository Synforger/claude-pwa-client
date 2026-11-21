"""The stream that follows the API tabs' record files and the wallets' spend files (`backend/api_tabs/api_tab_stream.py`):
what it publishes, where it starts, and what it keeps for the doors that list the tabs."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from backend._common.state import jsonl_event_broadcaster, sessions_overview
from backend.api_tabs import status_rows, stream, wallet_views
from backend.api_tabs.api_tab_stream import POLL_INTERVAL_SEC
from backend.tests.api_tabs.samples import (
    TAB_ID, append, assistant_row, tool_result_row, tool_use_row, user_row)

NOW = datetime.fromisoformat("2026-11-18T12:00:00+09:00")


def _drain(queue) -> list[tuple[dict, int | None]]:
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


def test_a_row_added_while_the_backend_runs_reaches_a_subscriber_within_two_seconds(api_env):
    append(api_env.record, user_row("u0", "before the backend started"))

    async def scenario():
        queue = jsonl_event_broadcaster.subscribe("all")
        task = asyncio.create_task(stream.run())
        try:
            await asyncio.sleep(POLL_INTERVAL_SEC * 2)                      # a few looks go by: nothing is new
            assert queue.empty()
            append(api_env.record, user_row("u1", "hello"))
            event, pos = await asyncio.wait_for(queue.get(), timeout=2)     # the design's bound
            assert (event["type"], event["text"], event["sid"], event["uuid"]) == ("user_message", "hello", TAB_ID, "u1")
            assert pos == api_env.record.stat().st_size
        finally:
            task.cancel()
            jsonl_event_broadcaster.unsubscribe("all", queue)

    asyncio.run(scenario())


def test_rows_that_were_already_there_when_the_backend_started_are_not_streamed(api_env):
    append(api_env.record, user_row("u1", "old"), assistant_row("a1", "m1", "old answer"))

    async def scenario():
        queue = jsonl_event_broadcaster.subscribe("all")
        try:
            await stream.poll()
            await stream.poll()
            assert queue.empty()
        finally:
            jsonl_event_broadcaster.unsubscribe("all", queue)

    asyncio.run(scenario())


def test_a_record_that_appears_after_the_start_is_streamed_from_its_first_row(api_env):
    async def scenario():
        queue = jsonl_event_broadcaster.subscribe("all")
        try:
            await stream.poll()                                             # the file is not there yet
            append(api_env.record, user_row("u1", "hello"), assistant_row("a1", "m1", "hi"))
            await stream.poll()
            return [event["type"] for event, _pos in _drain(queue)]
        finally:
            jsonl_event_broadcaster.unsubscribe("all", queue)

    assert asyncio.run(scenario()) == ["user_message", "assistant", "result"]    # a finished answer also yields its result


def test_every_kind_of_row_of_a_record_becomes_events_with_the_tab_id(api_env):
    append(api_env.record, user_row("u0", "start"))

    async def scenario():
        queue = jsonl_event_broadcaster.subscribe("all")
        try:
            await stream.poll()
            append(api_env.record, user_row("u1", "look it up"), tool_use_row("a1", "m1", "t1"),
                   tool_result_row("u2", "t1"), assistant_row("a2", "m2", "found it"))
            await stream.poll()
            return _drain(queue)
        finally:
            jsonl_event_broadcaster.unsubscribe("all", queue)

    items = asyncio.run(scenario())
    assert [event["type"] for event, _pos in items] == ["user_message", "assistant", "user", "assistant", "result"]
    assert {event["sid"] for event, _pos in items} == {TAB_ID}
    positions = [pos for _event, pos in items]
    assert positions == sorted(positions) and positions[-1] == api_env.record.stat().st_size


def test_a_record_that_got_shorter_sends_history_refetch_and_is_followed_from_zero(api_env):
    append(api_env.record, user_row("u1", "one"), user_row("u2", "two"))

    async def scenario():
        queue = jsonl_event_broadcaster.subscribe("all")
        try:
            await stream.poll()
            api_env.record.write_text("")
            append(api_env.record, user_row("u9", "fresh"))
            await stream.poll()
            return _drain(queue)
        finally:
            jsonl_event_broadcaster.unsubscribe("all", queue)

    events = [event for event, _pos in asyncio.run(scenario())]
    assert [event["type"] for event in events] == ["history_refetch", "user_message"]
    assert events[0]["sid"] == TAB_ID and events[0]["corr_id"] and events[1]["uuid"] == "u9"


def test_a_record_replaced_by_a_longer_file_sends_history_refetch_and_is_followed_from_zero(api_env):
    append(api_env.record, user_row("u1", "one"))

    async def scenario():
        queue = jsonl_event_broadcaster.subscribe("all")
        try:
            await stream.poll()
            fresh = api_env.record.with_name("fresh.jsonl")
            append(fresh, user_row("n1", "a new conversation"), user_row("n2", "already longer than the old one"))
            fresh.replace(api_env.record)
            await stream.poll()
            return _drain(queue)
        finally:
            jsonl_event_broadcaster.unsubscribe("all", queue)

    events = [event for event, _pos in asyncio.run(scenario())]
    assert [event["type"] for event in events] == ["history_refetch", "user_message", "user_message"]
    assert [event["uuid"] for event in events[1:]] == ["n1", "n2"]


def test_the_context_amount_is_kept_from_the_rows_read_and_a_change_wakes_the_overview(api_env):
    async def scenario():
        woken = sessions_overview.subscribe()
        try:
            await stream.poll()
            assert stream.context_tokens(TAB_ID) is None                    # no answer yet: none, never 0
            woken.clear()
            append(api_env.record, user_row("u1", "hi"), assistant_row("a1", "m1", "hello",
                                                                       usage={"input_tokens": 10, "cache_read_input_tokens": 90}))
            await stream.poll()
            assert stream.context_tokens(TAB_ID) == 100 and woken.is_set()
            woken.clear()
            append(api_env.record, user_row("u2", "and?"))                  # no new amount: nobody is woken
            await stream.poll()
            assert stream.context_tokens(TAB_ID) == 100 and not woken.is_set()
        finally:
            sessions_overview.unsubscribe(woken)

    asyncio.run(scenario())


def test_the_amount_is_known_from_the_start_without_reading_a_new_row(api_env):
    append(api_env.record, assistant_row("a1", "m1", "hi", usage={"input_tokens": 1, "cache_creation_input_tokens": 41}))
    asyncio.run(stream.poll())
    assert stream.context_tokens(TAB_ID) == 42


def test_a_row_that_is_not_json_is_skipped_and_written_to_the_log_once_a_minute(api_env, caplog):
    append(api_env.record, user_row("u0", "start"))

    async def scenario():
        queue = jsonl_event_broadcaster.subscribe("all")
        try:
            await stream.poll()
            with api_env.record.open("a") as handle:
                handle.write("{not json\n")
            append(api_env.record, user_row("u1", "after"))
            with caplog.at_level(logging.WARNING, logger="backend.api_tabs.api_tab_stream"):
                await stream.poll()
                with api_env.record.open("a") as handle:
                    handle.write("{still not json\n")
                await stream.poll()                                         # the same reason within a minute
            return [event["uuid"] for event, _pos in _drain(queue)]
        finally:
            jsonl_event_broadcaster.unsubscribe("all", queue)

    assert asyncio.run(scenario()) == ["u1"]                                # the bad rows cost the good one nothing
    lines = [r.getMessage() for r in caplog.records if " skipped: " in r.getMessage()]
    assert len(lines) == 1 and lines[0].startswith(f"api tab: {TAB_ID} line 2 skipped: not JSON")


def _spend(env, **fields) -> None:
    env.spend.write_text(json.dumps({"month": "2026-11", "spent": 123, "limit": 1000, "currency": "JPY",
                                     "updated_at": "2026-11-18T12:00:00+09:00", **fields}))


def _shown(env) -> dict | None:
    asyncio.run(stream.poll())
    return status_rows(NOW)[TAB_ID]["spend"]


def test_this_months_spend_is_shown_and_the_wallet_row_of_the_settings_screen_reads_it_too(api_env):
    _spend(api_env)
    expected = {"month": "2026-11", "spent": 123, "limit": 1000, "currency": "JPY",
                "updated_at": "2026-11-18T12:00:00+09:00"}
    assert _shown(api_env) == expected
    assert wallet_views(NOW) == [{"id": "api", "display_name": "API", "spend": expected}]


def test_last_months_spend_a_missing_file_and_a_broken_file_all_show_no_figure(api_env):
    _spend(api_env, month="2026-10")
    assert _shown(api_env) is None                                          # another month: no figure, not 0
    api_env.spend.unlink()
    assert _shown(api_env) is None
    api_env.spend.write_text("{broken")
    assert _shown(api_env) is None
    api_env.spend.write_text(json.dumps({"month": "2026-11", "spent": "lots", "limit": 1, "currency": "JPY"}))
    assert _shown(api_env) is None                                          # not the file the contract describes


def test_an_unreadable_spend_file_is_written_to_the_log_once_an_hour(api_env, caplog):
    api_env.spend.write_text("{broken")
    with caplog.at_level(logging.WARNING, logger="backend.api_tabs.api_tab_stream"):
        for _ in range(3):
            asyncio.run(stream.poll())
    lines = [r.getMessage() for r in caplog.records]
    assert len(lines) == 1 and lines[0].startswith("api account: api spend unreadable: not JSON")


def test_a_new_spend_figure_wakes_the_overview(api_env):
    async def scenario():
        woken = sessions_overview.subscribe()
        try:
            await stream.poll()
            woken.clear()
            _spend(api_env)
            await stream.poll()
            assert woken.is_set()
        finally:
            sessions_overview.unsubscribe(woken)

    asyncio.run(scenario())
