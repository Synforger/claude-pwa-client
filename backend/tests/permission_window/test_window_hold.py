"""The messages kept while a window is open (`permission_window/window_hold.py`): kept in a file, typed in order once the
screen has shown the input box on two looks in a row, dropped (and the sender told) when they cannot arrive."""
from __future__ import annotations

import asyncio
import json
import os
import stat

import pytest

from backend._common.state import jsonl_event_broadcaster
from backend.permission_window import window_hold as hold
from backend.permission_window import window_state as state
from backend.permission_window.window_screen import read_screen
from backend.tests.async_run import run
from backend.tests.permission_window import screens
from backend.tests.permission_window.conftest import SID


@pytest.fixture
def events(monkeypatch):
    published = []
    monkeypatch.setattr(jsonl_event_broadcaster, "publish", lambda sid, event: published.append((sid, event)))
    return published


def see(text: str, times: int = 1) -> None:
    for _ in range(times):
        state.note_screen(SID, read_screen(text))


async def patrol_and_wait() -> None:
    await hold.patrol(SID)
    typers = [task for task in hold._typers.values()]
    if typers:
        await asyncio.gather(*typers)


def test_a_kept_message_is_in_a_file_only_its_owner_reads(recorder):
    hold.keep(SID, "hello", "send-1", None)
    mode = stat.S_IMODE(os.stat(hold.WINDOW_HOLD_PATH).st_mode)
    assert mode == 0o600
    stored = json.loads(hold.WINDOW_HOLD_PATH.read_text())
    assert stored[SID][0]["text"] == "hello" and stored[SID][0]["conversation"] == "conv-1"
    assert [path.name for path in hold.WINDOW_HOLD_PATH.parent.iterdir()] == ["window_hold.json"]    # no temp file left


def test_the_file_is_read_again_when_the_backend_starts(recorder, monkeypatch):
    hold.keep(SID, "first", "send-1", None)
    hold.keep(SID, "second", None, "ses_other")
    monkeypatch.setattr(hold, "_kept", {})
    hold.load()
    assert [(entry.text, entry.send_id, entry.sender_tab) for entry in hold._kept[SID]] == [
        ("first", "send-1", None), ("second", None, "ses_other")]


def test_a_file_that_cannot_be_read_starts_with_nothing(recorder, monkeypatch):
    hold.WINDOW_HOLD_PATH.write_text("{ not json")
    monkeypatch.setattr(hold, "_kept", {})
    hold.load()
    assert hold._kept == {}


def test_messages_wait_while_the_window_is_on_the_screen_and_the_input_box_on_one_look(recorder):
    hold.keep(SID, "hello", None, None)
    see(screens.idle(), 1)
    run(patrol_and_wait())
    assert recorder.typed == []


def test_messages_are_typed_in_the_order_kept_once_the_input_box_shows_on_two_looks(recorder):
    hold.keep(SID, "first", None, None)
    hold.keep(SID, "second", None, "ses_other")
    see(screens.idle(), 2)
    run(patrol_and_wait())
    assert recorder.typed == [("first", None), ("second", "ses_other")]
    assert not hold.has_kept(SID) and json.loads(hold.WINDOW_HOLD_PATH.read_text()) == {}


def test_c_a_window_the_screen_never_showed_holds_nothing_for_ever(recorder):
    """Red before the fix: a window remembered from a hook that never showed held every message until the turn ended. The
    messages kept wait for the input box on two looks, whatever a hook said."""
    state.fold_row(SID, {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "ls"}}]}})
    state.open_window(SID, "Bash", {"command": "ls"}, "p1", now=1.0)
    hold.keep(SID, "hello", None, None)
    see(screens.idle(), 2)
    run(patrol_and_wait())
    assert recorder.typed == [("hello", None)]


def test_a_window_that_opens_again_keeps_the_message_in_front_and_the_rest_wait(recorder):
    hold.keep(SID, "first", None, None)
    hold.keep(SID, "second", None, None)
    recorder.answers.append({"ok": True, "held": "window"})
    see(screens.idle(), 2)
    run(patrol_and_wait())
    assert recorder.typed == [("first", None)]
    assert [entry.text for entry in hold._kept[SID]] == ["first", "second"]


def test_a_message_the_tab_did_not_take_is_told_to_its_screen_and_to_its_sender(recorder, events):
    hold.keep(SID, "to the tab", "send-9", "ses_other")
    recorder.answers.append({"ok": False, "reason": "not_ready"})
    see(screens.idle(), 2)
    run(patrol_and_wait())
    assert events == [(SID, {"type": "send_failed", "sid": SID, "send_id": "send-9"})]
    assert recorder.told == [("ses_other", SID, "to the tab", hold.NOT_TAKEN)]


def test_a_message_sent_while_the_others_are_typed_goes_behind_them(recorder):
    async def scenario():
        hold.keep(SID, "first", None, None)
        see(screens.idle(), 2)
        await hold.patrol(SID)
        assert hold.has_kept(SID)
        hold.keep(SID, "second", None, None)
        await asyncio.gather(*hold._typers.values())
    run(scenario())
    assert [text for text, _sender in recorder.typed] == ["first", "second"]


@pytest.mark.parametrize("tab_exists, claude_alive, reason", [(False, True, hold.NO_CLAUDE), (True, False, hold.NO_CLAUDE)])
def test_a_tab_that_is_closed_or_has_no_claude_drops_what_was_kept_for_it(recorder, events, tab_exists, claude_alive, reason):
    recorder.tab_exists, recorder.claude_alive = tab_exists, claude_alive
    hold.keep(SID, "lost", "send-1", "ses_other")
    see(screens.idle(), 2)
    run(patrol_and_wait())
    assert recorder.typed == [] and not hold.has_kept(SID)
    assert events == [(SID, {"type": "send_failed", "sid": SID, "send_id": "send-1"})]
    assert recorder.told == [("ses_other", SID, "lost", reason)]
    assert json.loads(hold.WINDOW_HOLD_PATH.read_text()) == {}


def test_d_messages_kept_for_an_earlier_conversation_are_dropped_not_typed_into_the_new_one(recorder, events):
    hold.keep(SID, "about the earlier talk", "send-1", "ses_other")
    recorder.conversation = "conv-2"
    hold.keep(SID, "for the new talk", None, None)
    see(screens.idle(), 2)
    run(patrol_and_wait())
    assert recorder.typed == [("for the new talk", None)]
    assert recorder.told == [("ses_other", SID, "about the earlier talk", hold.OTHER_CONVERSATION)]
    assert events == [(SID, {"type": "send_failed", "sid": SID, "send_id": "send-1"})]


def test_the_messages_of_a_restarted_backend_are_released_with_no_window_in_memory(recorder, monkeypatch):
    """After a restart the client remembers no window, and the file is what holds the messages: the patrol alone releases."""
    hold.keep(SID, "kept before the restart", None, None)
    monkeypatch.setattr(hold, "_kept", {})
    monkeypatch.setattr(state, "_tabs", {})
    hold.load()
    see(screens.idle(), 2)
    run(patrol_and_wait())
    assert recorder.typed == [("kept before the restart", None)]


def test_a_patrol_of_a_tab_with_nothing_kept_does_nothing(recorder):
    run(patrol_and_wait())
    assert recorder.typed == [] and recorder.told == []
