"""The send keys the backend typed, kept in a file so that a send posted again after a restart is still typed once.

The file has one `<sid>\t<key>` line per typed send, added at the end. `send_dedup.SendDedup` reads it once, the first
time it judges a send after the backend started, adds a line for every send it types, and writes it again with only
the keys it still remembers when the file has grown to twice that many.
"""
from __future__ import annotations

import logging

from backend._common.paths import SENT_KEYS_PATH
from backend._common.state import atomic_write_text

logger = logging.getLogger(__name__)


def load() -> list[tuple[str, str]]:
    """Every (sid, key) in the file, oldest first. → an empty list when there is no file or it cannot be read."""
    try:
        lines = SENT_KEYS_PATH.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError):
        logger.warning("sent keys could not be read, starting them again: %s", SENT_KEYS_PATH)
        return []
    pairs = []
    for line in lines:
        sid, separator, key = line.partition("\t")
        if separator and sid and key:
            pairs.append((sid, key))
    return pairs


def append(sid: str, key: str) -> None:
    """Add one typed send at the end of the file."""
    try:
        with SENT_KEYS_PATH.open("a", encoding="utf-8") as file:
            file.write(f"{sid}\t{key}\n")
    except OSError:
        logger.warning("sent key could not be written (a retry after a restart may be typed again): %s", SENT_KEYS_PATH)


def save(pairs: list[tuple[str, str]]) -> None:
    """Write the file again with only these (sid, key), oldest first."""
    try:
        atomic_write_text(SENT_KEYS_PATH, "".join(f"{sid}\t{key}\n" for sid, key in pairs))
    except OSError:
        logger.warning("sent keys could not be written again: %s", SENT_KEYS_PATH)


def can_store(sid: str, key: str) -> bool:
    """Whether a (sid, key) fits on one line of the file. A key that does not is still remembered in memory."""
    return not any(mark in text for text in (sid, key) for mark in ("\t", "\n", "\r"))
