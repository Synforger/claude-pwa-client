"""Reads and writes the settings file of a program that lists API tabs (the `settings` path of an `api_tab_sources` entry
in `config.json`), for the settings screen.

The path comes only from the client's own configuration, never from a file the program writes, so the program cannot
make the client write anywhere else. A write changes only the keys the screen sends, after they were judged against the
fields the program declared (`api_source_settings_values.py`); every other key keeps its value and place. The file is
replaced in one step (a temporary file in the same folder, then a rename), so the program never reads half a file.
Used by `settings/settings_view.py` (reads) and `routes/settings.py` (writes).
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from backend.api_tabs.api_source_settings_values import rejections, shown_values, with_values
from backend.api_tabs.api_tab_source_file import SettingsField
from backend.api_tabs.api_tab_sources import sources
from backend.api_tabs.api_tab_table import ApiTabSource, current_table

#: The mode a settings file gets when the screen writes it first (= a file the program and the operator read).
NEW_FILE_MODE = 0o644
#: The indent of the file the screen writes.
INDENT = 2
#: Why a source offers no settings to change: no settings file declared, no fields from the program yet, or a settings
#: file the screen cannot read (it does not write over it).
NO_SETTINGS = "no_settings"
NO_FIELDS = "no_fields"
SETTINGS_UNREADABLE = "settings_unreadable"

# One write at a time: each reads the file as it is, changes it and writes it back.
_lock = threading.Lock()


class SettingsRejected(ValueError):
    """The values may not be written; `reasons` says why, one line per value."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def read_settings(path: Path) -> dict | None:
    """The settings file's object, None when there is no file. Raises `OSError` when it cannot be read and `ValueError`
    when it is not a JSON object (= the screen does not write over a file it does not understand)."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        written = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"the settings file is not JSON: {error.msg}") from error
    if not isinstance(written, dict):
        raise ValueError("the settings file is not a JSON object")
    return written


def _replace(path: Path, settings: dict) -> None:
    """Put `settings` at `path` in one step, keeping the mode of the file it replaces."""
    try:
        mode = path.stat().st_mode & 0o777
    except FileNotFoundError:
        mode = NEW_FILE_MODE
    handle, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as tmp:
            tmp.write(json.dumps(settings, indent=INDENT, ensure_ascii=False) + "\n")
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def write_values(path: Path, fields: tuple[SettingsField, ...], values: object) -> dict:
    """Write `values` (= `{key: number}`) into the settings file at `path` (a link is followed, so the file it points
    to is replaced, not the link). → the file's new object. Raises `SettingsRejected` when a value may not be written
    (the file is not touched), `ValueError` when the file is not a JSON object, and `OSError` when it cannot be read or
    written (its folder missing, say)."""
    reasons = rejections(fields, values)
    if reasons:
        raise SettingsRejected(reasons)
    assert isinstance(values, dict)
    path = path.resolve()
    with _lock:
        settings = with_values(read_settings(path) or {}, fields, values)
        _replace(path, settings)
    return settings


def _source_view(source: ApiTabSource) -> dict:
    fields = sources.settings_fields(source.name) if source.settings is not None else ()
    problem, reason, values = None, None, {}
    if source.settings is None:
        problem = NO_SETTINGS
    elif not fields:
        problem = NO_FIELDS
    else:
        try:
            values = shown_values(fields, read_settings(source.settings))
        except (OSError, ValueError) as error:
            problem, reason, values = SETTINGS_UNREADABLE, str(error), shown_values(fields, None)
    return {"id": source.name, "fields": [settings_field.to_dict() for settings_field in fields], "values": values,
            "problem": problem, "reason": reason, "tabs_unreadable": sources.unreadable_reason(source.name)}


def source_views() -> list[dict]:
    """Each source as the settings screen shows it: the fields its program declared, their values now (the file's, or
    the default), why it offers none (a code, with the reason when the file cannot be read), and why its tab list file
    could not be read the last time it changed (None when it could)."""
    return [_source_view(source) for source in current_table().sources]
