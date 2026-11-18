"""What the tab list files of the `api_tab_sources` say now: the last reading of each file that could be read.

A program that runs several API tabs (one per LINE group, say) lists them in a file of its own instead of the operator
writing a row per tab into `config.json` (see `docs/reference/api-tabs.md`). The stream looks at each file every half
second and reads it again only when the file changed (or the configuration names another file). What a reading says
falls in two parts, kept apart so that every answer of the program does not rebuild the table of tabs:

- which tabs exist (name, title, record): a change bumps `identity_version`, and `api_tab_table.current_table()` builds
  the table again;
- the figures (context amount, window, spend, settings fields): the rows of the doors read them as they are now.

A file that is missing lists no tab. A file that cannot be read, is too large, or is not a tab list file keeps the last
reading (the program replaces the file in one step, so this is a broken program, not a write in progress). A row whose
record is not inside the folder of the tab list file is left out: the program says which file the client shows, and
must not be able to make it show another tab's conversation. The reading is blocking and runs in a worker thread; every
other thread reads only whole readings, which are never changed once made. Used by `api_tab_table.py` (rows),
`api_tab_rows.py` (figures), `api_source_settings.py` (fields) and `api_tab_stream.py` (looks).
"""
from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from backend.api_tabs.api_spend import file_signature
from backend.api_tabs.api_tab_source_file import (
    SettingsField, SourceFigures, SourceReading, SourceRow, parse_source_file)
from backend.api_tabs.log_throttle import LogThrottle

logger = logging.getLogger(__name__)

#: A file that stays broken, or a row that stays wrong across rewrites, is written to the log once an hour per reason.
LOG_INTERVAL_SEC = 3600.0
#: The largest tab list file that is read (= a few hundred groups fit many times over).
MAX_FILE_BYTES = 1024 * 1024
#: What a missing file lists: no tab, no figure.
EMPTY_READING = SourceReading(rows=(), figures={}, context_window=None, settings_fields=())


class ApiTabSources:
    """The last reading of each source's tab list file, and the version of which tabs they list."""

    def __init__(self) -> None:
        self.identity_version = 0
        self._readings: dict[str, SourceReading] = {}
        self._signatures: dict[str, tuple[Path, tuple[int, int, int] | None]] = {}
        self._unreadable: dict[str, str] = {}
        self._log = LogThrottle(LOG_INTERVAL_SEC)

    def rows(self, source: str) -> tuple[SourceRow, ...]:
        """The tabs the source lists now, in its order (none before its file was read)."""
        return self._reading(source).rows

    def figures(self, source: str, name: str) -> SourceFigures | None:
        """What the source says of its tab `name` now (None when it does not list the tab)."""
        return self._reading(source).figures.get(name)

    def context_window(self, source: str) -> int | None:
        """The size of the context window the source says (None when it says none)."""
        return self._reading(source).context_window

    def settings_fields(self, source: str) -> tuple[SettingsField, ...]:
        """The settings the source lets the settings screen change, in its order."""
        return self._reading(source).settings_fields

    def unreadable_reason(self, source: str) -> str | None:
        """Why the source's file could not be read the last time it changed (None when it was read, or is missing)."""
        return self._unreadable.get(source)

    def look(self, paths: dict[str, Path]) -> bool:
        """Read again every file of `paths` (= source name → file) that changed, and forget the sources that are no
        longer declared. → whether a figure changed (a change of the tabs bumps `identity_version`). Blocking."""
        figures_changed = self._forget(set(paths))
        for source, path in paths.items():
            signature = (path, file_signature(path))
            if self._signatures.get(source) == signature:
                continue
            self._signatures[source] = signature
            reading = self._read(source, path, signature[1] is not None)
            if reading is not None:
                figures_changed = self._keep(source, reading) or figures_changed
        return figures_changed

    def _reading(self, source: str) -> SourceReading:
        return self._readings.get(source, EMPTY_READING)

    def _read(self, source: str, path: Path, present: bool) -> SourceReading | None:
        """The file's reading: empty when it is missing, None (= keep the last one) when it cannot be read."""
        try:
            if not present:
                raise FileNotFoundError(path)
            with path.open("rb") as handle:
                data = handle.read(MAX_FILE_BYTES + 1)
            if len(data) > MAX_FILE_BYTES:
                raise ValueError(f"larger than {MAX_FILE_BYTES} bytes")
            reading = parse_source_file(data.decode("utf-8"))
        except FileNotFoundError:
            self._unreadable.pop(source, None)
            self._warn(source, "tabs", "tabs unreadable: file not found")
            return EMPTY_READING
        except (OSError, ValueError) as error:
            self._unreadable[source] = str(error)
            self._warn(source, "tabs", f"tabs unreadable: {error}")
            return None
        self._unreadable.pop(source, None)
        self._log.forget(f"{source}:tabs")
        reading = self._inside(path.parent, reading)
        for problem in reading.problems:
            self._warn(source, "row", problem)
        return reading

    @staticmethod
    def _inside(folder: Path, reading: SourceReading) -> SourceReading:
        """The reading without the rows whose record is not inside `folder` (links resolved)."""
        base = folder.resolve()
        rows, problems = [], list(reading.problems)
        for row in reading.rows:
            if row.record.resolve().is_relative_to(base):
                rows.append(row)
            else:
                problems.append(f"row skipped: {row.name}: record is not inside {base}")
        if len(rows) == len(reading.rows):
            return reading
        names = {row.name for row in rows}
        return replace(reading, rows=tuple(rows), problems=problems,
                       figures={name: figures for name, figures in reading.figures.items() if name in names})

    def _keep(self, source: str, reading: SourceReading) -> bool:
        """Keep a new reading. → whether a figure changed; a change of the tabs bumps `identity_version`."""
        previous = self._reading(source)
        self._readings[source] = reading
        if previous.rows != reading.rows:
            self.identity_version += 1
        return (previous.figures, previous.context_window, previous.settings_fields) != (
            reading.figures, reading.context_window, reading.settings_fields)

    def _forget(self, declared: set[str]) -> bool:
        """Drop what is kept of sources no longer declared. → whether one of them had a reading."""
        removed = [source for source in list(self._readings) if source not in declared]
        for source in removed:
            if self._readings.pop(source).rows:
                self.identity_version += 1
        for kept in (self._signatures, self._unreadable):
            for source in [source for source in list(kept) if source not in declared]:
                del kept[source]
        return bool(removed)

    def _warn(self, source: str, kind: str, reason: str) -> None:
        if self._log.allows(f"{source}:{kind}", reason):
            logger.warning("api source: %s %s", source, reason)


#: The one holder of the backend process; the stream fills it, the table and the rows read it.
sources = ApiTabSources()
