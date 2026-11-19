"""The names and rules the two machines of a ticket go by."""
from __future__ import annotations

import pytest

from backend.tickets import relay_judgement as judgement


@pytest.mark.parametrize("ticket, own, peers, home", [
    ("home-261119-01", "home", ["company"], judgement.HERE),
    ("company-261119-12", "home", ["company"], "company"),
    ("office-261119-01", "home", ["company"], None),
    ("home-261119-01", "home", [], judgement.HERE),
    ("company-261119-01", "home", [], None),
    ("not-an-id", "home", ["company"], None),
    ("my-mac-261119-01", "my.mac", ["company"], judgement.HERE),
    ("my-mac-261119-01", "home", ["my-mac"], "my-mac"),
])
def test_the_home_is_the_machine_named_at_the_head_of_the_id(ticket, own, peers, home):
    assert judgement.home_of(ticket, own, peers) == home


def test_a_tab_of_this_machine_is_its_bare_id_and_a_tab_of_the_other_has_its_machine_in_front():
    assert judgement.tab_of(None, "ses_a") == "ses_a" and judgement.tab_of("company", "ses_x") == "company:ses_x"


def test_a_line_written_by_a_tab_of_the_other_machine_names_the_machine_in_both_fields():
    assert judgement.writer_name("company", "ses_x", "notes") == ("company:ses_x", "notes @company")


@pytest.mark.parametrize("identity, seen", [
    ("ses_a", "home:ses_a"),             # a tab of the home, as the other machine reads it
    ("company:ses_x", "ses_x"),          # a tab of the other machine, which is its own to it
    ("office:ses_y", "office:ses_y"),    # a tab of any other machine stays
    ("", ""),
])
def test_a_tab_is_written_as_the_machine_that_reads_it_reads_it(identity, seen):
    assert judgement.seen_from(identity, "home", "company") == seen


def test_a_destination_without_a_machine_is_a_tab_of_the_machine_that_names_it():
    assert judgement.destination_of("notes", None, "company") == ("company", "notes")
    assert judgement.destination_of("home:notes", "home", "company") == ("home", "notes")


@pytest.mark.parametrize("named, party", [("home", None), ("company", "company"), ("office", judgement.THIRD)])
def test_a_machine_named_in_a_call_is_this_one_the_caller_or_a_third(named, party):
    assert judgement.machine_of_party(named, "home", "company") == party


def test_the_operators_own_words_are_the_lines_that_stay_on_the_home():
    assert set(judgement.OPERATOR_KINDS) == {"operator", "answered"}
