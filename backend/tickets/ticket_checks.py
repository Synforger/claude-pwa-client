"""The guard's judgements the tickets rest on, each one a command the configuration names (a key that is not there means
no judgement, as with `agent_message_check`):

- `ticket_place_check`: where a ticket opened by this tab is kept (the folder of its `tickets/`)
- `ticket_places_check`: every folder a ticket may be kept in
- `ticket_write_check`: whether a text may be added to the ticket kept in a place
- `ticket_covers_check`: whether a tab may read what is kept in a place (= may take part in its tickets)
- `ticket_read_check`: whether a tab may read one line of a ticket

A session is told to the guard as the tab's Claude conversation (the name of its record), as a message is; a tab with no
conversation yet is a `tier-tab:<id>` that has read nothing. Called by `ticket_service.py` and `ticket_places.py`.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from backend._common import config as _config
from backend._common import paths
from backend._common.errors import raise_error
from backend.terminal.runner import jsonl_path_for_session
from backend.tickets import guard_command, ticket_entry

#: How many lines of one ticket are judged at the same time when it is read
READ_PARALLEL = 8


def session_of(tab_id: str) -> str:
    """The tab's conversation as the guard knows it."""
    record = jsonl_path_for_session(tab_id)
    return record.stem if record is not None else f"tier-tab:{tab_id}"


async def decide_place(tab_id: str, typed_in_tab: str | None = None) -> Path:
    """The folder a ticket opened by `tab_id` is kept in; `typed_in_tab` is the tab where the operator typed the words the
    ticket quotes. Without the command, the folder outside every boundary (`paths.TICKETS_DIR`).

    The command prints the folder on its first line. Exit 1 means what the tab has read does not fit one place
    (`ticket_place_split`); any other failure, and a line that is not the path of a folder, is `ticket_place_unknown`."""
    command = _config.TICKET_PLACE_CHECK
    if not command:
        return paths.TICKETS_DIR
    names = {"session": session_of(tab_id), "typed_in": session_of(typed_in_tab) if typed_in_tab else ""}
    result = await guard_command.run_command(command, names)
    if result.status == 1:
        raise_error(409, "ticket_place_split",
                    f"このタブが読んだ境界は 1 つの置き場に収まりません。 境界をまたぐ形で頼んでください: {result.reason}")
    first = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
    if result.status != 0 or not Path(first).is_absolute():
        raise_error(503, "ticket_place_unknown", f"票の置き場を決められませんでした: {result.reason or first or 'no answer'}")
    return Path(first)


async def list_places() -> list[Path]:
    """Every folder the guard says a ticket may be kept in. Empty without the command or when it fails (= the places
    already known stay known)."""
    command = _config.TICKET_PLACES_CHECK
    if not command:
        return []
    result = await guard_command.run_command(command, {})
    if result.status != 0:
        return []
    return [Path(line.strip()) for line in result.stdout.splitlines() if Path(line.strip()).is_absolute()]


async def check_write(place: Path, text: str, typed_in_tab: str | None = None) -> None:
    """Judge a text before it is added to the ticket kept in `place` (= as a message to a reader that has read the whole
    place). Exit 1 refuses it with the reason; any other failure is `ticket_check_failed`."""
    command = _config.TICKET_WRITE_CHECK
    if not command:
        return
    names = {"place": str(place), "typed_in": session_of(typed_in_tab) if typed_in_tab else ""}
    result = await guard_command.run_command(command, names, text)
    if result.status == 0:
        return
    if result.status == 1:
        raise_error(403, "ticket_refused", f"票に書き足せませんでした: {result.reason}", reason=result.reason)
    raise_error(503, "ticket_check_failed", f"票への書き足しの検査を実行できませんでした: {result.reason}")


async def check_covers(tab_id: str, place: Path) -> None:
    """Make sure the tab has read the place's whole boundary, which is what lets it take part in the tickets kept there
    (`ticket_outside_place` otherwise)."""
    command = _config.TICKET_COVERS_CHECK
    if not command:
        return
    result = await guard_command.run_command(command, {"session": session_of(tab_id), "place": str(place)})
    if result.status is None:
        raise_error(503, "ticket_check_failed", f"票の置き場の検査を実行できませんでした: {result.reason}")
    if result.status != 0:
        raise_error(403, "ticket_outside_place",
                    "このタブは、 その票の置き場の境界を読めません。 境界をまたぐ形で頼んでください", id=tab_id)


async def filter_for_reader(reader_tab: str, entries: list[dict]) -> list[dict]:
    """The lines as `reader_tab` may see them: each line the guard does not let it read is replaced by
    `ticket_entry.hidden` (= a failed or missing run counts as not allowed)."""
    command = _config.TICKET_READ_CHECK
    if not command:
        return entries
    session = session_of(reader_tab)
    gate = asyncio.Semaphore(READ_PARALLEL)

    async def judge(entry: dict) -> dict:
        async with gate:
            result = await guard_command.run_command(command, {"session": session}, ticket_entry.judged_text(entry))
        return entry if result.status == 0 else ticket_entry.hidden(entry)

    return list(await asyncio.gather(*(judge(entry) for entry in entries)))
