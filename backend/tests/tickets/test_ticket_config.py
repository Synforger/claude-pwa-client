"""The configuration keys of the tickets: the guard's five commands and the machine's name."""
from __future__ import annotations

import pytest

import backend._common.config as config_mod
from backend.tests.tickets.samples import ticket_env, write_config  # noqa: F401


@pytest.mark.parametrize("name", config_mod.TICKET_CHECK_KEYS)
def test_a_check_is_the_list_of_words_the_configuration_gives_and_nothing_without_one(ticket_env, name):
    assert getattr(config_mod, name) == []
    write_config(ticket_env.guard._monkeypatch, ticket_env.root, **{name.lower(): ["peers.py", "--x", "{session}"]})
    assert getattr(config_mod, name) == ["peers.py", "--x", "{session}"]


@pytest.mark.parametrize("value", ["peers.py --x", ["peers.py", 3], {"a": 1}, None, 7])
def test_a_check_that_is_not_a_list_of_words_counts_as_no_check(ticket_env, value):
    write_config(ticket_env.guard._monkeypatch, ticket_env.root, ticket_write_check=value)
    assert config_mod.TICKET_WRITE_CHECK == []


def test_the_five_keys_are_the_ones_the_docs_name():
    assert [name.lower() for name in config_mod.TICKET_CHECK_KEYS] == [
        "ticket_place_check", "ticket_places_check", "ticket_write_check", "ticket_covers_check", "ticket_read_check"]


@pytest.mark.parametrize("value", ["", "  ", 5, None])
def test_a_machine_name_that_is_not_a_name_falls_back_to_the_host(ticket_env, value):
    import socket  # noqa: PLC0415
    write_config(ticket_env.guard._monkeypatch, ticket_env.root, machine_name=value)
    assert config_mod.MACHINE_NAME == socket.gethostname().split(".")[0]


def test_on_a_machine_whose_messages_the_guard_judges_every_ticket_key_left_out_is_named(ticket_env):
    write_config(ticket_env.guard._monkeypatch, ticket_env.root, agent_message_check=["peers.py"],
                 ticket_write_check=["peers.py"])
    assert config_mod.missing_ticket_checks() == [
        "ticket_place_check", "ticket_places_check", "ticket_covers_check", "ticket_read_check"]


def test_without_the_message_judgement_no_ticket_key_counts_as_missing(ticket_env):
    assert config_mod.missing_ticket_checks() == []
