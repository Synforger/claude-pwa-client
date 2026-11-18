"""The keys of the places: worked out by the backend, listed by the guard, kept in memory only."""
from __future__ import annotations

import hashlib

import pytest
from fastapi import HTTPException

from backend._common import paths
from backend.tests.async_run import run
from backend.tests.tickets.samples import ticket_env  # noqa: F401
from backend.tickets import ticket_index, ticket_places, ticket_service


def _boundary(env, name):
    (env.root / name).mkdir(exist_ok=True)
    return env.root / name / "tickets"


def test_a_key_is_the_first_sixteen_hex_digits_of_the_sha256_of_the_folders_path(ticket_env):
    folder = ticket_env.root / "company" / "tickets"
    assert ticket_places.key_of(folder) == hashlib.sha256(str(folder).encode()).hexdigest()[:16]
    assert len(ticket_places.key_of(folder)) == 16


def test_the_place_outside_every_boundary_is_known_without_asking_the_guard(ticket_env):
    assert run(ticket_places.folder_for(ticket_places.outside_key())) == paths.TICKETS_DIR
    assert ticket_env.guard.calls() == []


def test_a_boundarys_folder_is_never_written_to_the_index_only_its_key(ticket_env):
    folder = _boundary(ticket_env, "company")
    ticket_env.guard.use("place", place={"stdout": str(folder)})
    ticket = run(ticket_service.open_ticket("ses_a", "t", "x", operator_said=False))["id"]
    raw = (ticket_env.tickets / "index.json").read_text(encoding="utf-8")
    assert str(folder) not in raw and "company" not in raw
    assert ticket_index.get(ticket).place_key == ticket_places.key_of(folder)


def test_after_a_restart_the_places_are_listed_again_by_the_guard_and_the_ticket_is_found(ticket_env):
    folder = _boundary(ticket_env, "company")
    ticket_env.guard.use("place", "places", place={"stdout": str(folder)}, places={"stdout": f"{folder}\n/elsewhere/tickets"})
    ticket = run(ticket_service.open_ticket("ses_a", "A title", "x", operator_said=False))["id"]
    ticket_places.forget_all()                                                   # = the backend started again
    assert run(ticket_service.show("ses_b", ticket))["entries"][0]["title"] == "A title"
    assert len(ticket_env.guard.calls("places")) == 1


def test_the_guard_is_asked_for_the_places_once_per_start_not_per_ticket(ticket_env):
    folder = _boundary(ticket_env, "company")
    ticket_env.guard.use("place", "places", place={"stdout": str(folder)}, places={"stdout": str(folder)})
    ticket = run(ticket_service.open_ticket("ses_a", "t", "x", operator_said=False))["id"]
    ticket_places.forget_all()
    for _ in range(3):
        run(ticket_service.show("ses_b", ticket))
    assert len(ticket_env.guard.calls("places")) == 1


def test_a_key_the_guard_does_not_list_is_called_unknown_and_not_asked_for_again(ticket_env):
    ticket_env.guard.use("places", places={"stdout": ""})
    ticket_index.put("home-261119-01", ticket_index.IndexRow("feedfeedfeedfeed", "ses_a", "ses_a", "open", None))
    for _ in range(3):
        with pytest.raises(HTTPException) as refused:
            run(ticket_service.show("ses_b", "home-261119-01"))
        assert refused.value.detail["code"] == "ticket_place_unknown"
    assert len(ticket_env.guard.calls("places")) == 1                            # the first touch asked, and that was for this key too


def test_a_second_unknown_key_is_asked_for_once_more(ticket_env):
    ticket_env.guard.use("places", places={"stdout": ""})
    for key in ("feedfeedfeedfeed", "feedfeedfeedfeed", "beefbeefbeefbeef"):
        with pytest.raises(HTTPException):
            run(ticket_places.folder_for(key))
    assert len(ticket_env.guard.calls("places")) == 2


def test_a_key_that_shows_up_in_the_listing_later_is_found_by_the_one_asking(ticket_env):
    folder = _boundary(ticket_env, "company")
    ticket_env.guard.use("places", places={"stdout": ""})
    run(ticket_places.folder_for(ticket_places.outside_key()))
    ticket_env.guard.answer(places={"stdout": str(folder)})
    assert run(ticket_places.folder_for(ticket_places.key_of(folder))) == folder


def test_without_the_places_key_only_the_place_outside_is_known(ticket_env):
    with pytest.raises(HTTPException) as refused:
        run(ticket_places.folder_for("feedfeedfeedfeed"))
    assert refused.value.detail["code"] == "ticket_place_unknown"


def test_a_places_command_that_fails_leaves_what_is_known_as_it_was(ticket_env):
    folder = _boundary(ticket_env, "company")
    ticket_places.remember(folder)
    ticket_env.guard.use("places", places={"status": 2})
    assert run(ticket_places.folder_for(ticket_places.key_of(folder))) == folder
