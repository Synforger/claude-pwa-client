"""Tests of `backend/page_url/tailnet.py`: reading `tailscale serve status --json` through a stand-in command."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from backend.page_url import tailnet
from backend.page_url.page_url_refusal import PageUrlRefusal


def stand_in(tmp_path: Path, monkeypatch, body: str) -> Path:
    """Put a stand-in `tailscale` whose shell body is `body`, and make the module use it."""
    command = tmp_path / "tailscale"
    command.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    command.chmod(command.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(tailnet, "tailscale_command", lambda: str(command))
    return command


def test_the_status_comes_back_as_a_dict_and_the_command_is_asked_for_json(tmp_path, monkeypatch):
    stand_in(tmp_path, monkeypatch, 'echo "$@" > "$(dirname "$0")/args"; echo \'{"TCP": {"8776": {"HTTPS": true}}}\'')
    assert tailnet.serve_status() == {"TCP": {"8776": {"HTTPS": True}}}
    assert (tmp_path / "args").read_text().split() == ["serve", "status", "--json"]


def test_the_command_is_told_to_act_as_the_command_line_without_a_terminal(tmp_path, monkeypatch):
    # the macOS app's command, run by the resident backend, starts the app unless it is told (= its own switch)
    stand_in(tmp_path, monkeypatch,
             'if [ "$TAILSCALE_BE_CLI" = 1 ] && [ ! -t 0 ]; then echo "{}"; else echo "The Tailscale GUI failed to start"; fi')
    assert tailnet.serve_status() == {}


def test_nothing_served_is_an_empty_status(tmp_path, monkeypatch):
    stand_in(tmp_path, monkeypatch, "exit 0")
    assert tailnet.serve_status() == {}


@pytest.mark.parametrize("body, words", [
    ("echo 'not running' >&2; exit 1", "exit 1"),
    ("echo 'The Tailscale GUI failed to start'", "JSON ではありません: The Tailscale GUI failed to start"),
])
def test_a_failing_or_garbled_command_is_refused_with_the_reason(tmp_path, monkeypatch, body, words):
    stand_in(tmp_path, monkeypatch, body)
    with pytest.raises(PageUrlRefusal) as refusal:
        tailnet.serve_status()
    assert refusal.value.code == "page_tailnet_unavailable"
    assert words in refusal.value.message


def test_a_machine_without_the_command_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(tailnet.shutil, "which", lambda name: None)
    monkeypatch.setattr(tailnet, "TAILSCALE_APP_COMMAND", tmp_path / "missing")
    with pytest.raises(PageUrlRefusal) as refusal:
        tailnet.serve_status()
    assert refusal.value.code == "page_tailnet_unavailable"


def test_the_app_command_is_used_when_the_command_is_not_on_path(monkeypatch, tmp_path):
    app_command = tmp_path / "Tailscale"
    app_command.write_text("", encoding="utf-8")
    monkeypatch.setattr(tailnet.shutil, "which", lambda name: None)
    monkeypatch.setattr(tailnet, "TAILSCALE_APP_COMMAND", app_command)
    assert tailnet.tailscale_command() == str(app_command)
