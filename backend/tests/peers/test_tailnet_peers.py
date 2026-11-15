"""Reading a machine's place on the tailnet from `tailscale status --json` through a stand-in command (`peers/tailnet_peers.py`)."""
from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from backend.page_url.page_url_refusal import PageUrlRefusal
from backend.peers import tailnet_peers

STATUS = {"Self": {"TailscaleIPs": ["100.64.0.1"], "Online": True}, "Peer": {
    "nodekey:aaa": {"TailscaleIPs": ["100.64.0.2", "fd7a::2"], "Online": False, "LastSeen": "2026-11-12T10:02:13.123456789Z"},
    "nodekey:bbb": {"TailscaleIPs": ["100.64.0.3"], "Online": True, "LastSeen": "2026-11-16T01:00:00Z"},
    "nodekey:ccc": {"TailscaleIPs": ["100.64.0.4"], "Online": False, "LastSeen": "0001-01-01T00:00:00Z"},
}}


def stand_in(tmp_path: Path, monkeypatch, body: str) -> None:
    command = tmp_path / "tailscale"
    command.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    command.chmod(command.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(tailnet_peers, "tailscale_command", lambda: str(command))


def prints(tmp_path: Path, monkeypatch, status: object) -> None:
    (tmp_path / "status.json").write_text(json.dumps(status))
    stand_in(tmp_path, monkeypatch, f'cat "$(dirname "$0")/status.json"; echo "$@" > "$(dirname "$0")/args"')


def test_a_machine_off_the_tailnet_says_when_it_was_last_seen(tmp_path, monkeypatch):
    prints(tmp_path, monkeypatch, STATUS)
    assert tailnet_peers.peer_status("100.64.0.2") == {"online": False, "last_seen": "2026-11-12T10:02:13.123456789Z"}
    assert (tmp_path / "args").read_text().split() == ["status", "--json"]


def test_a_machine_on_the_tailnet_is_online(tmp_path, monkeypatch):
    prints(tmp_path, monkeypatch, STATUS)
    assert tailnet_peers.peer_status("100.64.0.3") == {"online": True, "last_seen": "2026-11-16T01:00:00Z"}


def test_a_machine_never_seen_has_no_last_seen_time(tmp_path, monkeypatch):
    prints(tmp_path, monkeypatch, STATUS)
    assert tailnet_peers.peer_status("100.64.0.4") == {"online": False, "last_seen": None}


@pytest.mark.parametrize("address", ["100.64.0.99", "127.0.0.1"])
def test_an_address_no_machine_of_the_tailnet_has_cannot_be_told(tmp_path, monkeypatch, address):
    prints(tmp_path, monkeypatch, STATUS)
    assert tailnet_peers.peer_status(address) == {"online": None, "last_seen": None}


@pytest.mark.parametrize("body", ["exit 1", "echo 'The Tailscale GUI failed to start'", "echo '[1]'", "echo '{\"Peer\": 3}'"])
def test_a_failing_or_garbled_command_cannot_be_told(tmp_path, monkeypatch, body):
    stand_in(tmp_path, monkeypatch, body)
    assert tailnet_peers.peer_status("100.64.0.2") == {"online": None, "last_seen": None}


def test_a_machine_without_the_command_cannot_be_told(monkeypatch):
    def missing() -> str:
        raise PageUrlRefusal("page_tailnet_unavailable", "no tailscale")
    monkeypatch.setattr(tailnet_peers, "tailscale_command", missing)
    assert tailnet_peers.peer_status("100.64.0.2") == {"online": None, "last_seen": None}


def test_the_command_is_told_to_act_as_the_command_line_without_a_terminal(tmp_path, monkeypatch):
    # the macOS app's command, run by the resident backend, starts the app unless it is told (= its own switch)
    (tmp_path / "status.json").write_text(json.dumps(STATUS))
    stand_in(tmp_path, monkeypatch,
             'if [ "$TAILSCALE_BE_CLI" = 1 ]; then cat "$(dirname "$0")/status.json"; else echo "GUI failed to start"; fi')
    assert tailnet_peers.peer_status("100.64.0.3")["online"] is True
