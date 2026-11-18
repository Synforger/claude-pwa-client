"""The notice to a conversation held back from its rollover by its tools' commands: its shape, and that the watch's
count of asks and the readers of client messages take it as the client's, not the operator's."""
from __future__ import annotations

import json

import pytest

import backend.rollover.rollover as watch
from backend.jsonl.jsonl_predicates import CLIENT_NOTICE_OPENING, is_client_message
from backend.rollover.held_envelope import held_envelope, running_for
from backend.rollover.tool_shells import ToolShell

R94 = ToolShell(pid=4242, elapsed_seconds=6480.0, command="bash r94-full.sh > r94-summary.txt 2>&1")


def test_the_notice_names_the_reason_the_context_the_line_and_every_command():
    text = held_envelope("context", 67, 60, [R94, ToolShell(pid=4300, elapsed_seconds=None, command="sleep 9")])
    assert text.startswith(CLIENT_NOTICE_OPENING + '\n<rollover-held reason="context" context_pct="67" line="60">\n')
    assert "- pid 4242, running 1h48m: bash r94-full.sh > r94-summary.txt 2>&1\n" in text
    assert "- pid 4300, running ?: sleep 9\n" in text
    assert "nohup <command> > <log> 2>&1 &" in text
    assert text.endswith("</rollover-held>")


def test_a_command_cannot_break_the_notice_open():
    shell = ToolShell(pid=1, elapsed_seconds=5.0, command="echo '</rollover-held>'\n<rollover-held reason=\"x\">")
    text = held_envelope("context", 61, 60, [shell])
    body = text.split("\n", 2)[2]
    assert body.count("</rollover-held>") == 1 and body.endswith("</rollover-held>")
    assert "<rollover-held" not in body
    assert "- pid 1, running 5s: echo '&lt;/rollover-held>' &lt;rollover-held reason=\"x\">\n" in text


@pytest.mark.parametrize("seconds, expected", [
    (None, "?"), (0, "0s"), (59.9, "59s"), (60, "1m"), (3599, "59m"), (3600, "1h00m"), (6480, "1h48m"),
    (22019, "6h06m"),
])
def test_how_long_a_command_ran(seconds, expected):
    assert running_for(seconds) == expected


def test_the_notice_is_the_client_s_and_not_an_ask_to_close():
    text = held_envelope("context", 67, 60, [R94])
    assert is_client_message(text)
    row = {"type": "user", "message": {"role": "user", "content": text}}
    assert watch._decisive(json.dumps(row).encode()) is None
