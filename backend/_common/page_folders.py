"""Which files the page origin serves: the folders the configuration lists (`page_origin.folders`).

Called by `backend/_common/config.py` (to name a mistake in the list), by the page origin's routes and by
`tabs page-url`. This file only judges strings: it reads no file and no configuration.

A listed folder is written relative to the page origin's folder and is served with everything below it. A segment `*`
is one folder and `**` is any number of them. Neither stands for a name that starts with `.` or `_`: such a folder is
served only below a listed one, or when the list names it.
"""

from __future__ import annotations

import unicodedata

ONE_FOLDER = "*"
ANY_FOLDERS = "**"
#: The first characters of the names a wildcard does not stand for.
UNLISTED_STARTS = (".", "_")


def is_served(path: str, folders: tuple[str, ...] | None) -> bool:
    """Whether the page origin serves `path` (= relative to its folder, resolved).

    path (str): the file, with `/` between the names
    folders (tuple[str, ...] | None): the list; None serves the whole folder
    """
    if folders is None:
        return True
    parents = _names(path)[:-1]
    return any(_covers(_names(folder), parents) for folder in folders)


def folder_list_problem(value: object) -> str | None:
    """What is wrong with the list as the configuration has it, None when nothing is (or it is not written)."""
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(entry, str) for entry in value):
        return "config.page_origin.folders must be a list of folders"
    for entry in value:
        if not _is_folder_entry(entry):
            return f"config.page_origin.folders: {entry!r} is not a folder relative to page_origin.folder"
    return None


def _is_folder_entry(entry: str) -> bool:
    names = entry.split("/")
    if any(name in ("", ".", "..") for name in names) or names[-1] == ANY_FOLDERS:
        return False  # a list that ends with `**` would cover everything above it too
    return all(name in (ONE_FOLDER, ANY_FOLDERS) or ONE_FOLDER not in name for name in names)


def _names(path: str) -> list[str]:
    # the disk and a URL may spell the same name in different Unicode forms
    return unicodedata.normalize("NFC", path).split("/")


def _covers(listed: list[str], parents: list[str]) -> bool:
    """Whether `parents` begins with a path `listed` stands for."""
    reached = _past_any_folders(listed, {0})
    for name in parents:
        if len(listed) in reached:
            return True
        is_standable = not name.startswith(UNLISTED_STARTS)
        following: set[int] = set()
        for at in reached:
            if listed[at] == ANY_FOLDERS:
                if is_standable:
                    following.add(at)
            elif listed[at] == ONE_FOLDER:
                if is_standable:
                    following.add(at + 1)
            elif listed[at] == name:
                following.add(at + 1)
        reached = _past_any_folders(listed, following)
        if not reached:
            return False
    return len(listed) in reached


def _past_any_folders(listed: list[str], reached: set[int]) -> set[int]:
    """`reached`, with the positions after each `**` in it, which may stand for no folder."""
    found = set(reached)
    for at, name in enumerate(listed):
        if at in found and name == ANY_FOLDERS:
            found.add(at + 1)
    return found
