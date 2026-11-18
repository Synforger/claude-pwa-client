"""The launcher for an agent with no launch script keeps the alias's arguments on every start
(`backend/cli/claude_launcher.py`)."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.cli import claude_launcher

ALIAS = ["--model", "opus", "--tools", "", "--strict-mcp-config"]


@pytest.fixture
def started(monkeypatch):
    lines: list[list[str]] = []
    monkeypatch.setattr(claude_launcher.os, "execvpe", lambda file, line, environment: lines.append(line))
    monkeypatch.setattr(claude_launcher, "CLAUDE", "claude")
    return lines


def test_a_new_conversation_starts_with_the_first_message_and_the_file_is_removed(tmp_path, started):
    message = tmp_path / "first"
    message.write_text("Describe the tavern.\nIn two lines.", encoding="utf-8")
    claude_launcher.main([*ALIAS, "--first-message-file", str(message)])
    assert started == [["claude", *ALIAS, "Describe the tavern.\nIn two lines."]]
    assert not message.exists()


def test_a_reopened_conversation_keeps_the_aliases_arguments(started):
    claude_launcher.main([*ALIAS, "--resume", "11111111-2222"])
    assert started == [["claude", *ALIAS, "--resume", "11111111-2222"]]


def test_a_first_message_that_starts_with_a_dash_is_not_read_as_an_option(tmp_path, started):
    message = tmp_path / "first"
    message.write_text("--- scene 1 ---", encoding="utf-8")
    claude_launcher.main(["--first-message-file", str(message)])
    assert started == [["claude", " --- scene 1 ---"]]


def test_a_first_message_file_that_cannot_be_read_starts_nothing(tmp_path, started):
    assert claude_launcher.main(["--first-message-file", str(tmp_path / "gone")]) == 1
    assert started == []


def test_the_words_are_split_wherever_they_stand():
    words = claude_launcher.parse(["--resume", "abc", "--model", "opus"])
    assert words == claude_launcher.LaunchWords(["--model", "opus"], None, "abc")
    assert claude_launcher.parse(["--model", "opus"]).first_message_file is None
    assert claude_launcher.parse(["--first-message-file", "/tmp/x"]).first_message_file == Path("/tmp/x")


def test_claude_starts_without_the_api_keys(monkeypatch):
    environments: list[dict[str, str]] = []
    monkeypatch.setattr(claude_launcher.os, "execvpe", lambda file, line, environment: environments.append(environment))
    monkeypatch.setattr(claude_launcher.os, "environ", {"HOME": "/home/someone", "ANTHROPIC_API_KEY": "sk-one",
                                                        "ANTHROPIC_AUTH_TOKEN": "token", "PWA_SID": "ses_head"})
    claude_launcher.main(["--resume", "abc"])
    assert environments == [{"HOME": "/home/someone", "PWA_SID": "ses_head"}]
