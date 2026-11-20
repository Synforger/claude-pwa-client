"""A message sent to a tab that has no claude yet reaches the new conversation once (`terminal/first_message.py` and
`terminal/receipt.py` together).

`tabs ask` and `tabs send` type into a tab whose pane holds a shell: the typing starts the claude, and the sender then
waits for the record to show the message. The launch owns the text from then on (as the first message, or held to be
typed once the claude is up), so the wait only watches. A wait that typed the text again, because the record of a
conversation that has not begun shows nothing yet, put it in the new conversation a second time.

Only the pane and the claude that starts in it are faked: the launch, the holding and the receipt are the real ones.
"""
from __future__ import annotations

import asyncio
import json

import pytest

import backend.terminal.first_message as fm
import backend.terminal.receipt as receipt
import backend.terminal.routes as routes
from backend.jsonl.jsonl_predicates import AGENT_MESSAGE_OPENING
from backend.terminal import input_ready

SID = "ses_fresh"
CLAUDE_SCREEN = "some history\n╭─────╮\n│ >   │\n╰─────╯\n  5h:12% ctx:3%"
ASK = "こんにちは。港町を舞台に、短い一場面を書いてください。"
FROM_TAB = (AGENT_MESSAGE_OPENING + "\n<agent-message>\nPlease look at the build.\n</agent-message>")
BOOT_SEC = 0.05


class _Meta:
    """The part of a tab's record the launch reads: a tab that remembers no tier and has no conversation to reopen."""
    tier_tab = None
    tier = None
    child = False
    parent_id = None

    def sleeping_claude_sid(self):
        return None


class _Claude:
    """The claude that starts in the pane: what its record shows, what was typed into it, and what the launcher gave it."""

    def __init__(self, record):
        self.record = record
        self.running = False
        self.typed: list[str] = []
        self.first_given: str | None = None

    def start(self, first_message: str) -> None:
        self.first_given = first_message
        self.running = True
        self.add_row(first_message)
        input_ready.mark_ready(SID)

    def add_row(self, text: str) -> None:
        with self.record.open("a") as out:
            out.write(json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n")

    def rows_of(self, text: str) -> int:
        head = " ".join(text.split())[:30]
        rows = [json.loads(line) for line in self.record.read_text().splitlines()]
        return sum(" ".join(row["message"]["content"].split()).startswith(head) for row in rows)


@pytest.fixture
def pane(monkeypatch, tmp_path):
    """A launcher tab with a shell in its pane. Typing the launch command starts a `_Claude` a moment later (= the
    record is bound once it has started, not before)."""
    claude = _Claude(tmp_path / "record.jsonl")
    bound = {"path": None}
    sent_files: list = []

    def keys(_sid, text=None, key=None, enter=False):
        if text and "--first-message-file" in text:
            file = text.split("--first-message-file ", 1)[1]
            sent_files.append(file)

            def boot():
                claude.record.write_text("")
                bound["path"] = claude.record
                claude.start(open(file, encoding="utf-8").read())
            asyncio.get_running_loop().call_later(BOOT_SEC, boot)
        return True

    async def nothing(*_a, **_k):
        return None

    async def typeable(_sid, _timeout):
        return True

    async def pty_send(session_id, payload, key=None):
        """What `routes.pty_send` does with a text: held while a launch starts, else a launch, else typed."""
        text = payload["text"]
        if (held := fm.hold_while_launching(session_id, text)) is not None:
            return held
        if (launched := await fm.launch_with_first_message(session_id, text)) is not None:
            return launched
        claude.typed.append(text)
        claude.add_row(text)
        return {"ok": True, "confirmed": True}

    monkeypatch.setattr(fm, "uses_launcher", lambda _sid: True)
    monkeypatch.setattr(fm, "claude_in_pane", lambda _sid: claude.running)
    monkeypatch.setattr(fm, "first_message_command", lambda _sid, path: f"agent_a --first-message-file {path}")
    monkeypatch.setattr(fm, "resume_command_for", lambda _sid: None)
    monkeypatch.setattr(fm, "ensure_pty_session_for", nothing)
    monkeypatch.setattr(fm, "register_claude_when_ready", nothing)
    monkeypatch.setattr(fm, "wait_until_typeable", typeable)
    monkeypatch.setattr(fm, "tmux_send_keys", keys)
    monkeypatch.setattr(fm, "_uploads_dir", lambda: tmp_path / "uploads")
    monkeypatch.setitem(fm.sessions_meta, SID, _Meta())
    monkeypatch.setattr(routes, "pty_send", pty_send)
    monkeypatch.setattr(receipt, "pty_send", pty_send)
    monkeypatch.setattr(receipt, "pane_text", lambda _sid: CLAUDE_SCREEN)
    monkeypatch.setattr(receipt, "jsonl_path_for_session", lambda _sid: bound["path"])
    monkeypatch.setattr(receipt, "tmux_send_keys", keys)
    monkeypatch.setattr(receipt, "SCREEN_LOOK_SEC", 0.01)
    monkeypatch.setattr(input_ready, "LAUNCH_LOOK_SEC", 0.005)
    input_ready.forget(SID)
    fm._held.pop(SID, None)
    yield claude
    input_ready.forget(SID)
    fm._held.pop(SID, None)
    fm._typers.pop(SID, None)


async def _deliver_then_let_the_rest_happen(text: str) -> bool:
    taken = await receipt.deliver_to_woken(SID, text)
    await asyncio.sleep(0.5)  # a second copy, if there is one, is typed once the claude is up
    return taken


def test_a_question_to_a_tab_with_no_claude_is_the_first_message_and_is_not_typed_again(pane):
    assert asyncio.run(_deliver_then_let_the_rest_happen(ASK)) is True
    assert pane.first_given == ASK
    assert pane.typed == []
    assert pane.rows_of(ASK) == 1


def test_a_message_from_a_tab_starts_the_envelope_and_is_typed_once(pane):
    assert asyncio.run(_deliver_then_let_the_rest_happen(FROM_TAB)) is True
    assert pane.first_given.startswith("Tab opened by the client for its tier")
    assert pane.typed == [FROM_TAB]
    assert pane.rows_of(FROM_TAB) == 1


def test_a_message_whose_launch_never_showed_it_is_not_said_to_be_taken(pane, monkeypatch):
    # The launch announces itself but the record never shows the text: the sender is told, and nothing is typed again.
    monkeypatch.setattr(receipt, "SCREEN_WAIT_SEC", 0.05)
    monkeypatch.setattr(receipt, "RESCUE_SEC", 0.1)
    monkeypatch.setattr(pane, "add_row", lambda _text: None)
    assert asyncio.run(_deliver_then_let_the_rest_happen(ASK)) is False
    assert pane.typed == []
