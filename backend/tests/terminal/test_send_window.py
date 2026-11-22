"""What is typed to a tab while Claude Code may have a window open (`terminal/routes.py`, `permission_window/`).

The screen is read inside the typing lock before the text is cleared and before the Enter: a window on the screen takes
no text at all (its Enter takes the first choice, a digit of the text may be a choice), whatever the client remembers. A
message of a person or another tab is kept; a command of the client is refused; the answers to a question or a plan, the chips
and the person's answer words are for the person's door only. tmux and claude are not started: the pane of
`test_send_one_at_a_time` records the keys, and the screens are those of `permission_window/screens.py`.
"""
from __future__ import annotations

import asyncio
import json

import pytest

import backend.permission_window.window_answer as window_answer
import backend.permission_window.window_hold as window_hold
import backend.terminal.routes as routes
import backend.terminal.runner as runner
from backend._common.state import StreamState, agent_status, sessions_meta
from backend.permission_window import window_state
from backend.permission_window.window_screen import read_screen
from backend.tests.async_run import run
from backend.tests.permission_window import screens
from backend.tests.permission_window.conftest import call_row
from backend.tests.terminal.test_send_one_at_a_time import pane, send  # noqa: F401  (pane is a fixture)

SID = "ses_a"
LS = {"command": "ls -la"}


@pytest.fixture
def drawn(pane, monkeypatch, tmp_path):  # noqa: F811
    """What the pane draws (`drawn["text"]`, or the next of `drawn["sequence"]`), the recorder of what the kept messages are
    told with, and the tab `ses_a` with no window known."""
    shown = {"text": screens.idle(), "sequence": [], "told": [], "typed_answers": []}

    def capture(_sid, lines=70):
        return shown["sequence"].pop(0) if shown["sequence"] else shown["text"]

    async def type_kept(session_id, text, sender_tab):
        return await routes.pty_send(session_id, {"text": text, "enter": True}, None, hold=True, sender=sender_tab,
                                     releasing=True)

    async def alive(_sid):
        return True

    async def tell(sender_tab, session_id, text, reason):
        shown["told"].append((sender_tab, text, reason))

    monkeypatch.setattr(runner, "capture_pane_ansi_tail", capture)
    monkeypatch.setattr(window_answer, "note_user_input", lambda _sid: None)

    async def poke(_sid):
        return None
    monkeypatch.setattr(window_answer, "poke_now", poke)
    monkeypatch.setitem(agent_status, SID, {"pending_plan": None, "pending_permission": None})
    monkeypatch.setitem(sessions_meta, SID, object())
    monkeypatch.setattr(window_state, "_tabs", {})
    monkeypatch.setattr(window_state.jsonl_watcher, "get_jsonl_for", lambda _sid: None)
    monkeypatch.setattr(window_hold, "_kept", {})
    monkeypatch.setattr(window_hold, "_typers", {})
    monkeypatch.setattr(window_hold, "_loaded", True)
    monkeypatch.setattr(window_hold, "WINDOW_HOLD_PATH", tmp_path / "window_hold.json")
    monkeypatch.setattr(window_hold, "_wiring", window_hold.Wiring(
        send=type_kept, tab_exists=lambda _sid: True, claude_alive=alive, conversation_of=lambda _sid: "conv-1",
        tell_sender=tell))
    return shown


def a_window(drawn, screen=None, *, tool="Bash", tool_input=LS, hook=True):
    """The record's call, the hook's input and the look of the detector: an approval window on the screen."""
    drawn["text"] = screens.approval(tool_input.get("command", "")) if screen is None else screen
    window_state.fold_row(SID, call_row("toolu_1", tool, tool_input))
    if hook:
        window_state.open_window(SID, tool, tool_input, "p1", now=1.0)
    window_state.note_screen(SID, read_screen(drawn["text"]))


def input_looks(drawn, times=2):
    drawn["text"] = screens.idle()
    for _ in range(times):
        window_state.note_screen(SID, read_screen(drawn["text"]))


def typed_keys(pane):  # noqa: F811
    return [what for _sid, what in pane["keys"]]


def from_the_person(text, **rest):
    return run(routes.pty_send_from_person(SID, {"text": text, "enter": True, **rest}, None))


# --- a message of a person or another tab -------------------------------------------------------------------------------

def test_a_text_is_kept_while_an_approval_window_is_on_the_screen_and_nothing_is_typed(pane, drawn):  # noqa: F811
    a_window(drawn)
    assert run(routes.pty_send(SID, {"text": "a message", "enter": True}, None, hold=True)) == {"ok": True, "held": "window"}
    assert pane["keys"] == [] and pane["delivered"] == []
    assert [entry.text for entry in window_hold._kept[SID]] == ["a message"]


def test_a_command_of_the_client_is_refused_at_a_window_and_is_not_kept(pane, drawn):  # noqa: F811
    a_window(drawn)
    assert run(send(SID, "a rollover ask")) == {"ok": False, "reason": "window_open"}
    assert pane["keys"] == [] and not window_hold.has_kept(SID)


def test_a_command_with_no_hold_argument_is_a_command(pane, drawn):  # noqa: F811
    """The default is to refuse: a caller that forgets the argument does not count a kept message as asked."""
    a_window(drawn)
    assert run(routes.pty_send(SID, {"text": "x", "enter": True}, None))["reason"] == "window_open"


def test_a_text_at_a_window_of_a_plan_and_of_a_question_is_kept_too(pane, drawn):  # noqa: F811
    for tool, screen in (("ExitPlanMode", screens.question()), ("AskUserQuestion", screens.question())):
        window_state.close_all(SID, "test")
        a_window(drawn, screen, tool=tool, tool_input={"plan": "x"}, hook=False)
        assert run(routes.pty_send(SID, {"text": "typed at it", "enter": True}, None, hold=True))["held"] == "window"
    assert pane["keys"] == []


def test_a_text_at_a_window_nothing_is_known_of_is_refused_not_kept(pane, drawn):  # noqa: F811
    """A picker (`/model`): a digit typed there changes its choice and Enter confirms it, and the text would be typed after it
    closed as an utterance of its own."""
    drawn["text"] = screens.picker()
    result = run(routes.pty_send(SID, {"text": "2", "enter": True}, None, hold=True))
    assert result == {"ok": False, "reason": "window_open"} and pane["keys"] == []


def test_d_a_window_after_a_restart_is_kept_by_what_the_screen_shows_and_the_record_says(pane, drawn, tmp_path, monkeypatch):  # noqa: F811
    """Red before the fix: with no window in memory (the backend started after the hook) a text was typed at the window."""
    record = tmp_path / "conv.jsonl"
    record.write_text("".join(json.dumps(row) + "\n" for row in [
        {"type": "user", "message": {"content": "do it"}}, call_row("toolu_1", "Bash", {"command": "rm x"})]))
    monkeypatch.setattr(window_state.jsonl_watcher, "get_jsonl_for", lambda _sid: record)
    drawn["text"] = screens.approval("rm x")
    assert run(routes.pty_send(SID, {"text": "a message", "enter": True}, None, hold=True)) == {"ok": True, "held": "window"}
    assert pane["keys"] == []


def test_c_a_hook_the_screen_never_showed_does_not_hold_texts(pane, drawn):  # noqa: F811
    """Red before the fix: a window remembered from a hook that never reached the screen held every text for ever."""
    window_state.fold_row(SID, call_row("toolu_1", "Bash", LS))
    window_state.open_window(SID, "Bash", LS, "p1", now=1.0)
    drawn["text"] = screens.idle()
    run(routes.pty_send(SID, {"text": "plain", "enter": True}, None, hold=True))
    assert [said for _sid, said in pane["delivered"]] == ["plain"]


def test_e_numbers_in_a_reply_are_no_window_for_a_text(pane, drawn):  # noqa: F811
    """Red before the fix: `1. Yes` and `2. No` in a reply were read as a window's choices."""
    window_state.fold_row(SID, call_row("toolu_1", "Bash", LS))
    window_state.open_window(SID, "Bash", LS, "p1", now=1.0)
    drawn["text"] = screens.numbers_in_a_reply()
    run(routes.pty_send(SID, {"text": "plain", "enter": True}, None, hold=True))
    assert [said for _sid, said in pane["delivered"]] == ["plain"]


def test_w7_a_window_that_appears_while_the_text_is_typed_gets_no_enter(pane, drawn):  # noqa: F811
    """The screen is read before the text is cleared (the input box) and again before the Enter (now a window): the Enter is
    not typed, and the message is kept."""
    drawn["sequence"] = [screens.idle(), screens.approval("ls -la")]
    window_state.fold_row(SID, call_row("toolu_1", "Bash", LS))
    result = run(routes.pty_send(SID, {"text": "a message", "enter": True}, None, hold=True))
    assert result == {"ok": True, "held": "window"}
    assert "enter" not in typed_keys(pane)
    assert [entry.text for entry in window_hold._kept[SID]] == ["a message"]


def test_w7_a_window_that_is_already_there_before_the_text_is_cleared_gets_no_key_at_all(pane, drawn):  # noqa: F811
    drawn["sequence"] = [screens.approval("ls -la")]
    window_state.fold_row(SID, call_row("toolu_1", "Bash", LS))
    run(routes.pty_send(SID, {"text": "1", "enter": True}, None, hold=True))
    assert pane["keys"] == []


def test_a_text_with_a_file_is_kept_at_a_window_and_says_which_files_were_saved(pane, drawn, monkeypatch):  # noqa: F811
    a_window(drawn)

    async def saved(_files, _sid):
        return [{"name": "p.jpg", "path": "/tmp/p.jpg"}]
    monkeypatch.setattr(routes, "save_to_tmp", saved)
    monkeypatch.setattr(routes, "wait_ready", lambda _sid: asyncio.sleep(0, result=True))
    result = run(routes.pty_send_with_files(SID, text="look", files=[], idempotency_key=None))
    assert result["held"] == "window" and result["saved_files"] == [{"name": "p.jpg", "path": "/tmp/p.jpg"}]
    assert pane["keys"] == []


# --- order and release --------------------------------------------------------------------------------------------------

def test_what_is_kept_is_typed_before_a_text_sent_after_the_input_box_shows_on_two_looks(pane, drawn):  # noqa: F811
    window_hold.keep(SID, "kept first", None, None)
    input_looks(drawn, 2)
    run(routes.pty_send(SID, {"text": "sent now", "enter": True}, None, hold=True))
    assert [said for _sid, said in pane["delivered"]] == ["kept first", "sent now"]


def test_a_text_sent_on_the_first_look_of_the_input_box_goes_behind_what_is_kept(pane, drawn):  # noqa: F811
    window_hold.keep(SID, "kept first", None, None)
    input_looks(drawn, 1)
    assert run(routes.pty_send(SID, {"text": "sent now", "enter": True}, None, hold=True))["held"] == "window"
    assert [entry.text for entry in window_hold._kept[SID]] == ["kept first", "sent now"]
    assert pane["delivered"] == []


def test_the_patrol_types_what_is_kept_once_no_window_is_left_and_in_order(pane, drawn):  # noqa: F811
    a_window(drawn)
    run(routes.pty_send(SID, {"text": "first", "enter": True}, None, hold=True))
    run(routes.pty_send(SID, {"text": "second", "enter": True}, None, hold=True))
    input_looks(drawn, 2)

    async def scenario():
        await window_hold.patrol(SID)
        await asyncio.gather(*window_hold._typers.values())
    run(scenario())
    assert [said for _sid, said in pane["delivered"]] == ["first", "second"]


# --- answers: words, chips, questions and plans ----------------------------------------------------------------------------

def test_the_answer_word_of_a_person_answers_the_window_and_is_not_sent(pane, drawn):  # noqa: F811
    a_window(drawn)
    result = from_the_person("許可")
    assert result == {"ok": True, "answered": "allow", "message": "窓に答えました"}
    assert typed_keys(pane) == ["paste:1"] and pane["delivered"] == []
    assert window_state.is_open(SID) is False


def test_a_deny_word_answers_with_the_no_line(pane, drawn):  # noqa: F811
    a_window(drawn)
    from_the_person("だめ")
    assert typed_keys(pane) == ["paste:2"]


def test_a_word_a_voice_heard_answers_too(pane, drawn):  # noqa: F811
    a_window(drawn)
    assert from_the_person("[voice] 許可")["answered"] == "allow"


def test_an_answer_word_at_a_window_a_key_does_not_answer_is_kept_like_any_text(pane, drawn):  # noqa: F811
    a_window(drawn, screens.three_choices())
    assert from_the_person("許可") == {"ok": True, "held": "window"}
    assert pane["keys"] == []


def test_an_answer_word_before_the_detector_has_shown_the_window_is_kept(pane, drawn):  # noqa: F811
    window_state.fold_row(SID, call_row("toolu_1", "Bash", LS))
    window_state.open_window(SID, "Bash", LS, "p1", now=1.0)
    drawn["text"] = screens.approval("ls -la")
    assert from_the_person("許可") == {"ok": True, "held": "window"}
    assert pane["keys"] == []


def test_yes_in_japanese_is_not_an_answer(pane, drawn):  # noqa: F811
    a_window(drawn)
    assert from_the_person("はい") == {"ok": True, "held": "window"}
    assert pane["keys"] == []


def test_the_answer_word_with_the_input_box_on_the_screen_is_an_utterance_like_any_other(pane, drawn):  # noqa: F811
    input_looks(drawn, 2)
    from_the_person("許可")
    assert [said for _sid, said in pane["delivered"]] == ["許可"]


def test_4_the_answer_word_does_not_answer_when_it_comes_through_pty_send_directly(pane, drawn):  # noqa: F811
    """Another tab's message and the client's commands come through `pty_send`: the words are judged in the person's door only."""
    a_window(drawn)
    assert run(routes.pty_send(SID, {"text": "許可", "enter": True}, None, hold=True)) == {"ok": True, "held": "window"}
    assert pane["keys"] == [] and window_state.is_open(SID)


def test_an_answer_to_a_question_is_typed_at_its_window_by_the_persons_door(pane, drawn):  # noqa: F811
    window_state.fold_row(SID, call_row("toolu_q", "AskUserQuestion", {"questions": []}))
    drawn["text"] = screens.question()
    window_state.note_screen(SID, read_screen(drawn["text"]))
    result = from_the_person("2", answers_choice=True)
    assert result["ok"] is True and [said for _sid, said in pane["delivered"]] == ["2"]


def test_an_answer_to_a_plan_is_typed_at_its_window_and_carries_no_voice_mark(pane, drawn, monkeypatch):  # noqa: F811
    window_state.fold_row(SID, call_row("toolu_p", "ExitPlanMode", {"plan": "x"}))
    drawn["text"] = screens.question()
    monkeypatch.setattr(routes, "is_voice_open", lambda _sid: True)
    from_the_person("1", answers_choice=True)
    assert [said for _sid, said in pane["delivered"]] == ["1"]


def test_a_the_second_press_of_a_plan_answer_does_not_answer_the_approval_that_came_after_it(pane, drawn):  # noqa: F811
    """Red before the fix: a second press of the plan's button typed its digit at the next window, which it had not seen."""
    a_window(drawn)
    result = from_the_person("1", answers_choice=True)
    assert result == {"ok": False, "reason": "window_open"} and pane["keys"] == []


def test_an_answer_to_a_question_that_is_gone_is_refused_and_not_an_utterance(pane, drawn):  # noqa: F811
    input_looks(drawn, 2)
    assert from_the_person("1", answers_choice=True) == {"ok": False, "reason": "window_open"}
    assert pane["keys"] == []


def test_4_answers_choice_in_the_payload_of_a_direct_call_is_not_read(pane, drawn):  # noqa: F811
    """The flag is the person's door's: a payload given to `pty_send` directly carries it for nothing."""
    a_window(drawn)
    result = run(routes.pty_send(SID, {"text": "1", "enter": True, "answers_choice": True}, None, hold=True))
    assert result == {"ok": True, "held": "window"} and pane["keys"] == []
    assert run(routes.pty_send(SID, {"text": "1", "enter": True, "answers_choice": True}, None))["reason"] == "window_open"


def test_a_chip_is_typed_at_a_question_and_refused_at_an_approval(pane, drawn):  # noqa: F811
    window_state.fold_row(SID, call_row("toolu_q", "AskUserQuestion", {"questions": []}))
    drawn["text"] = screens.question()
    assert run(routes.pty_send_raw_key(SID, {"key": "2"})) == {"ok": True}
    assert typed_keys(pane) == ["paste:2"]
    window_state.close_all(SID, "test")
    pane["keys"].clear()
    a_window(drawn)
    assert run(routes.pty_send_raw_key(SID, {"key": "1"})) == {"ok": False, "reason": "window_open"}
    assert pane["keys"] == []


def test_a_chip_is_typed_when_the_input_box_is_on_the_screen(pane, drawn):  # noqa: F811
    input_looks(drawn, 2)
    assert run(routes.pty_send_raw_key(SID, {"key": "Y", "enter": True})) == {"ok": True}
    assert typed_keys(pane) == ["paste:Y", "enter"]


def test_a_digit_without_an_enter_is_refused_at_an_approval_and_typed_at_a_question(pane, drawn):  # noqa: F811
    a_window(drawn)
    assert run(routes.pty_send(SID, {"text": "2"}, None)) == {"ok": False, "reason": "window_open"}
    window_state.close_all(SID, "test")
    window_state.fold_row(SID, call_row("toolu_q", "AskUserQuestion", {"questions": []}))
    drawn["text"] = screens.question()
    assert run(routes.pty_send(SID, {"text": "2"}, None)) == {"ok": True}
    assert typed_keys(pane) == ["paste:2"]


def test_a_single_key_such_as_a_persons_escape_is_never_kept(pane, drawn):  # noqa: F811
    a_window(drawn)
    assert run(routes.pty_send(SID, {"key": "C-c"}, None)) == {"ok": True}
    assert typed_keys(pane) == ["key:C-c"]


# --- voice --------------------------------------------------------------------------------------------------------------

def test_a_voice_never_types_an_escape_at_a_window(pane, drawn, monkeypatch):  # noqa: F811
    a_window(drawn)
    monkeypatch.setattr(routes, "stream_states", {SID: StreamState(busy=True)})
    assert run(routes.interrupt_for_voice(SID)) is False
    assert "key:Escape" not in typed_keys(pane)


def test_a_voice_text_is_kept_at_a_window_without_an_escape(pane, drawn, monkeypatch):  # noqa: F811
    a_window(drawn)
    monkeypatch.setattr(routes, "stream_states", {SID: StreamState(busy=True)})
    result = from_the_person(routes.VOICE_INPUT_MARK + " please go on")
    assert result == {"ok": True, "held": "window"} and typed_keys(pane) == []


def test_a_voice_interrupt_still_types_its_escape_when_no_window_is_open(pane, drawn, monkeypatch):  # noqa: F811
    input_looks(drawn, 2)
    monkeypatch.setattr(routes, "stream_states", {SID: StreamState(busy=True)})
    monkeypatch.setattr(routes, "_escape_settled", lambda _sid, _sent: asyncio.sleep(0, result=routes._Escaped(True, False)))
    assert run(routes.interrupt_for_voice(SID)) is True
    assert "key:Escape" in typed_keys(pane)


# --- 7: with no window, everything goes as before ---------------------------------------------------------------------------

@pytest.mark.parametrize("hold", [True, False])
def test_with_the_input_box_on_the_screen_a_text_is_typed_as_before(pane, drawn, hold):  # noqa: F811
    input_looks(drawn, 2)
    assert run(routes.pty_send(SID, {"text": "plain", "enter": True}, None, hold=hold)).get("held") is None
    assert [said for _sid, said in pane["delivered"]] == ["plain"]
    assert typed_keys(pane)[:1] == ["wipe"] and not window_hold.has_kept(SID)


def test_with_a_screen_that_is_neither_a_text_is_typed_as_before(pane, drawn):  # noqa: F811
    drawn["text"] = "$ \n"
    run(routes.pty_send(SID, {"text": "plain", "enter": True}, None, hold=True))
    assert [said for _sid, said in pane["delivered"]] == ["plain"]


def test_an_utterance_of_a_person_with_no_window_goes_through_the_persons_door_as_before(pane, drawn):  # noqa: F811
    input_looks(drawn, 2)
    assert from_the_person("hello there").get("held") is None
    assert [said for _sid, said in pane["delivered"]] == ["hello there"]


def test_a_message_of_another_tab_with_no_window_is_typed_as_before(pane, drawn):  # noqa: F811
    input_looks(drawn, 2)
    assert run(routes.pty_send(SID, {"text": "from a tab", "enter": True}, None, hold=True, sender="ses_b")).get("held") is None
    assert [said for _sid, said in pane["delivered"]] == ["from a tab"]


def test_a_plan_approval_with_no_plan_window_open_is_not_answered_blind(pane, drawn):  # noqa: F811
    """With the plan gone from the screen its answer is refused (W5), not typed into the input box as a message."""
    input_looks(drawn, 2)
    assert from_the_person("1", answers_choice=True)["ok"] is False and pane["delivered"] == []


# --- version 4 ---------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("hold", [True, False])
@pytest.mark.parametrize("typed", ["1. fix the test", "1. Yes", "1. Yes\n  2. No"])
def test_g1_a_text_that_begins_with_a_number_is_sent_like_any_other(pane, drawn, hold, typed):  # noqa: F811
    """Red before the fix: once pasted into the box, `❯ 1. …` was read as the marked line of a window, the Enter was not typed
    and the text was refused or kept: an ordinary message could not be sent."""
    drawn["text"] = screens.idle()
    drawn["sequence"] = [screens.idle(), screens.idle_with_typed(typed)]
    result = run(routes.pty_send(SID, {"text": typed, "enter": True}, None, hold=hold))
    assert result.get("held") is None and result.get("reason") is None
    assert [said for _sid, said in pane["delivered"]] == [typed] and "enter" in typed_keys(pane)


def test_g1_g6_the_usual_screen_of_a_tab_with_a_title_and_a_status_line_takes_a_text(pane, drawn):  # noqa: F811
    drawn["text"] = screens.idle_with_typed("", title="tab name")
    run(routes.pty_send(SID, {"text": "hello", "enter": True}, None, hold=True))
    assert [said for _sid, said in pane["delivered"]] == ["hello"]


@pytest.mark.parametrize("key", ["Enter", "Down", "Up", "1", "y", "Tab", "Space"])
def test_g9_a_key_or_a_bare_enter_is_refused_at_an_approval(pane, drawn, key):  # noqa: F811
    """Red before the fix: a send with no text and an Enter, or any key but Escape, never went through the look, and Enter
    allowed the window."""
    a_window(drawn)
    payload = {"enter": True} if key == "Enter" else {"key": key}
    assert run(routes.pty_send(SID, payload, None)) == {"ok": False, "reason": "window_open"}
    assert pane["keys"] == []


def test_g9_a_bare_enter_with_text_none_and_key_enter_is_refused_too(pane, drawn):  # noqa: F811
    a_window(drawn)
    assert run(routes.pty_send(SID, {"key": "Enter"}, None)) == {"ok": False, "reason": "window_open"}
    assert run(routes.pty_send(SID, {"text": "", "enter": True}, None))["ok"] is False


def test_g9_escape_and_control_c_are_the_persons_stop_and_pass_at_a_window(pane, drawn):  # noqa: F811
    a_window(drawn)
    assert run(routes.pty_send(SID, {"key": "C-c"}, None)) == {"ok": True}
    assert typed_keys(pane) == ["key:C-c"]


def test_g9_a_bare_enter_and_a_key_pass_at_a_question_and_with_the_input_box(pane, drawn):  # noqa: F811
    window_state.fold_row(SID, call_row("toolu_q", "AskUserQuestion", {"questions": []}))
    drawn["text"] = screens.question()
    assert run(routes.pty_send(SID, {"key": "Down"}, None)) == {"ok": True}
    assert run(routes.pty_send(SID, {"key": "Enter"}, None)) == {"ok": True}
    input_looks(drawn, 2)
    assert run(routes.pty_send(SID, {"key": "Enter"}, None)) == {"ok": True}
    assert typed_keys(pane) == ["key:Down", "key:Enter", "key:Enter"]


def test_g11_a_question_the_record_does_not_hold_yet_takes_the_persons_answer_and_keeps_messages(pane, drawn):  # noqa: F811
    """Red before the fix: the window of a question the record did not hold was a window nothing is known of: the answer was
    refused, so the question that is open now could not be answered by the chat."""
    window_state.note_choice_hook(SID, "AskUserQuestion")
    drawn["text"] = screens.question()
    window_state.note_screen(SID, read_screen(drawn["text"]))
    assert run(routes.pty_send(SID, {"text": "typed at it", "enter": True}, None, hold=True))["held"] == "window"
    assert from_the_person("2", answers_choice=True)["ok"] is True
    assert [said for _sid, said in pane["delivered"]] == ["2"]


def test_g11_the_hook_of_an_answered_question_does_not_keep_a_later_picker_a_question(pane, drawn):  # noqa: F811
    window_state.note_choice_hook(SID, "AskUserQuestion")
    input_looks(drawn, 2)
    drawn["text"] = screens.picker()
    assert run(routes.pty_send(SID, {"text": "2", "enter": True}, None, hold=True)) == {"ok": False, "reason": "window_open"}


def test_g15_the_send_id_of_a_text_kept_for_a_window_is_the_one_given_or_the_idempotency_key(pane, drawn):  # noqa: F811
    a_window(drawn)
    run(routes.pty_send(SID, {"text": "one", "enter": True}, "key-1", hold=True))
    run(routes.pty_send(SID, {"text": "two", "enter": True}, None, hold=True, send_id="send-2"))
    assert [(entry.text, entry.send_id) for entry in window_hold._kept[SID]] == [("one", "key-1"), ("two", "send-2")]
