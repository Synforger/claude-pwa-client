"""Which folder a place key stands for. The index names a ticket's place by a key (the first 16 hex digits of the SHA-256
of the folder's absolute path), never by the path, so the folders of the boundaries are listed only here, in memory: asked
of the guard (`ticket_places_check`) when the first ticket is touched and once more when a key is not known, and never
written to a file. The place outside every boundary is always known. Called by `ticket_service.py`.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from backend._common import paths
from backend._common.errors import raise_error
from backend.tickets import ticket_checks

KEY_LENGTH = 16
_known: dict[str, Path] = {}
_asked = False
_missed: set[str] = set()


def key_of(folder: Path) -> str:
    """The key of the place whose `tickets/` folder is `folder`."""
    return hashlib.sha256(str(folder).encode("utf-8")).hexdigest()[:KEY_LENGTH]


def outside_key() -> str:
    """The key of the place outside every boundary (= worked out here, not asked of the guard)."""
    return key_of(paths.TICKETS_DIR)


def remember(folder: Path) -> str:
    """Take `folder` as a place (= the guard named it when a ticket was opened) and give its key."""
    _known[key_of(folder)] = folder
    return key_of(folder)


def forget_all() -> None:
    """Drop everything known, so that the guard is asked again (= for the tests and for a changed configuration)."""
    global _asked
    _known.clear()
    _missed.clear()
    _asked = False


async def _ask_guard() -> None:
    global _asked
    _asked = True
    for folder in await ticket_checks.list_places():
        remember(folder)


async def folder_for(key: str) -> Path:
    """The folder of a place key. A key not known is looked for once by asking the guard for its places; `ticket_place_unknown`
    when it is not among them."""
    if key == outside_key():
        return paths.TICKETS_DIR
    asked_now = not _asked
    if asked_now:
        await _ask_guard()
    if key not in _known and key not in _missed and not asked_now:
        await _ask_guard()
    if key not in _known:
        _missed.add(key)
        raise_error(409, "ticket_place_unknown", "この票の置き場の folder が分かりません (検査コマンドの置き場の一覧に無い)")
    return _known[key]
