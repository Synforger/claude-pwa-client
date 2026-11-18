"""The id of a ticket: its form, and that only that form is taken as a file name (`backend/tickets/ticket_id.py`)."""
from __future__ import annotations

from datetime import date

import pytest

from backend.tickets import ticket_id


def test_an_id_is_the_machine_the_day_and_a_number_of_two_digits():
    assert ticket_id.ticket_id("home", date(2026, 11, 19), 1) == "home-261119-01"
    assert ticket_id.ticket_id("home", date(2026, 11, 19), 12) == "home-261119-12"
    assert ticket_id.ticket_id("home", date(2026, 11, 19), 100) == "home-261119-100"


def test_the_year_is_in_the_id_so_the_same_day_of_next_year_is_another_ticket():
    assert ticket_id.ticket_id("home", date(2026, 11, 19), 1) != ticket_id.ticket_id("home", date(2027, 11, 19), 1)


@pytest.mark.parametrize(("name", "written"), [
    ("home", "home"), ("Dev-MacBook", "Dev-MacBook"), ("my mac.local", "my-mac-local"), ("../x", "x"), ("", "machine"),
])
def test_a_machine_name_is_written_with_letters_digits_and_dashes(name, written):
    assert ticket_id.machine_part(name) == written


@pytest.mark.parametrize("text", ["home-261119-01", "Dev-MacBook-261119-02", "home-261119-100"])
def test_a_made_id_has_the_form_of_an_id(text):
    assert ticket_id.is_ticket_id(text)


@pytest.mark.parametrize("text", ["", "../home-261119-01", "home-261119-1", "home-261119-01/x", "home/261119/01", "261119-01",
                                  "home-261119-01\n"])
def test_a_text_that_is_not_an_id_is_not_taken_as_a_file_name(text):
    assert not ticket_id.is_ticket_id(text)
