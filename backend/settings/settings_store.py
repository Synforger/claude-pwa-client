"""Reads and writes `config.json` for the settings screen: applies a partial update (`settings_fields.apply_update`) to
the file as it is now, writes the result in place (a temporary file in the same folder, then a rename, so a reader never
sees half a file), and has the client read it again (`config.reload_config`), so that the next look of the patrols
works with the new values.

Every other field is written back with the value and the position it had; the file keeps its indent. Used by
`routes/settings.py`.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

import backend._common.config as config
from backend.settings.settings_fields import apply_update

logger = logging.getLogger(__name__)

# The indent used when the file has none to copy.
DEFAULT_INDENT = 2
# Only one update at a time: each reads the file as it is, changes it and writes it back.
_lock = threading.Lock()


def _indent_of(text: str) -> int | str:
    """The indent of the first indented line of `text`: a count of spaces, or a tab."""
    found = re.search(r'^([ \t]+)\S', text, re.MULTILINE)
    if found is None:
        return DEFAULT_INDENT
    return "\t" if found.group(1).startswith("\t") else len(found.group(1))


def _write(path: Path, settings: dict[str, Any], original: str) -> None:
    """Replace the file at `path` with `settings` (the mode of the file is kept)."""
    text = json.dumps(settings, indent=_indent_of(original), ensure_ascii=False)
    if original.endswith("\n"):
        text += "\n"
    handle, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as tmp:
            tmp.write(text)
        os.chmod(tmp_name, path.stat().st_mode & 0o777)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def update_settings(update: object) -> list[str]:
    """Apply a partial update to `config.json` and read the file again. → the paths it changed. Raises
    `settings_fields.Rejected` for an update that is not allowed (the file is not touched), and `OSError` or `ValueError`
    when the file cannot be read or written."""
    path = Path(config.CONFIG_PATH).resolve()
    with _lock:
        original = path.read_text(encoding="utf-8")
        current = json.loads(original)
        if not isinstance(current, dict):
            raise ValueError(f"{path} does not hold an object")
        updated, changed = apply_update(current, update)
        _write(path, updated, original)
        config.reload_config()
    logger.info("settings: changed %s", ", ".join(changed))
    return changed
