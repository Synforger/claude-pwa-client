"""Move the tickets that sit outside every boundary but hold what may not be kept there into the place the guard names for
them. Such a ticket was written while the guard's judgements of the tickets were not configured (= nothing judged where
it went or what went in). Run once when the backend starts, after which every ticket is judged as it is written.
Called by `main.py`.

A ticket is judged by its file's lines as they are written (= with the names and tiers of the tabs that wrote them, not
only the texts the guard judges when a line is added), and moved to the place the guard gives for the tab that opened
it, as when it was opened. A ticket the guard cannot place, or that does not fit the place it gives, stays where it is
and is named in the log, for a person to decide.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import HTTPException

from backend._common import config as _config
from backend._common import paths
from backend.tickets import guard_command, ticket_checks, ticket_entry, ticket_file, ticket_index, ticket_places, ticket_wake

logger = logging.getLogger(__name__)


def _raw_text(folder: Path, ticket: str) -> str:
    try:
        return ticket_file.path_of(folder, ticket).read_text(encoding="utf-8")
    except OSError:
        return ""


async def _fits(folder: Path, text: str, typed_in_tab: str | None = None) -> bool | None:
    """Whether `text` may be kept in `folder` (= the guard's write judgement, with the operator's words counted as typed in
    `typed_in_tab` when given). None when the judgement could not run."""
    typed_in = ticket_checks.session_of(typed_in_tab) if typed_in_tab else ""
    result = await guard_command.run_command(_config.TICKET_WRITE_CHECK, {"place": str(folder), "typed_in": typed_in}, text)
    return None if result.status not in (0, 1) else result.status == 0


def _typed_in(entries: list[dict]) -> str | None:
    """The tab where the operator typed the words the ticket quotes (= its `operator` line), or None."""
    return next((entry.get("typed_in") for entry in entries
                 if entry.get("kind") == ticket_entry.OPERATOR and isinstance(entry.get("typed_in"), str)), None)


def _move(ticket: str, source: Path, folder: Path) -> bool:
    """Move the ticket's file into `folder` and point its row there, both under the ticket's lock. → False when the
    ticket was moved or changed place meanwhile."""
    with ticket_file.lock_for(ticket), ticket_index.locked():
        row = ticket_index.get(ticket)
        if row is None or row.place_key != ticket_places.outside_key():
            return False
        target = ticket_file.path_of(folder, ticket)
        if target.exists():
            return False
        folder.mkdir(parents=True, exist_ok=True)
        shutil.move(str(ticket_file.path_of(source, ticket)), str(target))
        ticket_index.put(ticket, row._replace(place_key=ticket_places.remember(folder)))
    return True


async def _relocate_one(ticket: str, opener: str) -> str:
    """Judge and, when it must, move one ticket kept outside every boundary. → what happened (= for the log)."""
    outside = paths.TICKETS_DIR
    raw = _raw_text(outside, ticket)
    if not raw:
        return "no file"
    fits_outside = await _fits(outside, raw)
    if fits_outside is None:
        return "stays: the write judgement could not run"
    if fits_outside:
        return "fits"
    typed_in = _typed_in(ticket_entry.parse_lines(raw))
    try:
        folder = await ticket_checks.decide_place(opener, typed_in)
    except HTTPException as error:
        return f"stays: no place for its opener ({error.detail.get('code')})"
    if folder == outside or not folder.parent.is_dir():
        return "stays: its opener's place is outside every boundary"
    if not await _fits(folder, raw, typed_in):
        return "stays: it does not fit its opener's place either"
    if not _move(ticket, outside, folder):
        return "changed meanwhile"
    return f"moved to place {ticket_places.key_of(folder)}"


async def relocate_outside_tickets() -> dict[str, str]:
    """Judge every ticket kept outside every boundary, and move each that may not stay there. Nothing is done without the
    guard's place and write judgements. → what happened to each ticket judged, by id."""
    if not (_config.TICKET_PLACE_CHECK and _config.TICKET_WRITE_CHECK):
        return {}
    outcomes: dict[str, str] = {}
    for ticket, row in ticket_index.rows().items():
        if row.place_key != ticket_places.outside_key():
            continue
        outcomes[ticket] = await _relocate_one(ticket, row.opener)
        if outcomes[ticket].startswith("stays"):
            logger.warning("ticket relocate: %s %s", ticket, outcomes[ticket])
        elif outcomes[ticket].startswith("moved"):
            logger.info("ticket relocate: %s %s", ticket, outcomes[ticket])
    if any(outcome.startswith("moved") for outcome in outcomes.values()):
        ticket_wake.wake()
    return outcomes
