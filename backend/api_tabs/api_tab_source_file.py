"""What a tab list file holds: the file a program writes to list the API tabs it runs (`api_tab_sources` in
`config.json`, see `docs/reference/api-tabs.md`).

The program rewrites the whole file each time (a temporary file renamed over it). One row is one tab; the program also
says how much of the context each conversation holds (it decides when to roll a conversation over, so only it knows the
amount right after one), this month's spend of each tab, the size of the context window, and the fields of its settings
that the settings screen may change. Pure: the text comes in, the reading goes out, no file is touched. Used by
`api_tab_sources.py`.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from backend.api_tabs.api_spend import Spend, parse_spend

#: The names a row may have (= the characters of a declared tab's, `api_tab_table.NAME_RE`; the length keeps the id, which
#: goes into URLs and subscription queries, short).
ROW_NAME_RE = re.compile(r"[a-z0-9-]{1,64}")
#: The keys a settings field may have: the program's own setting names.
FIELD_KEY_RE = re.compile(r"[a-z0-9_]+")


@dataclass(frozen=True)
class SourceRow:
    """What a row says about which tab exists: its name, the title the list shows and its record file. A change of any of
    these changes the table of tabs."""
    name: str
    title: str
    record: Path


@dataclass(frozen=True)
class SourceFigures:
    """What a row says that changes with every answer: the context amount (None when there is none) and this month's
    spend as the program wrote it (None when the row has none)."""
    context_tokens: int | None
    spend: Spend | None


@dataclass(frozen=True)
class SettingsField:
    """One setting of the program that the settings screen may change: a number between `min` and `max`, on the grid of
    `step` from `min` when there is one, `default` while the settings file does not set it."""
    key: str
    label: str
    unit: str | None
    min: float
    max: float
    step: float | None
    default: float

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "unit": self.unit, "min": self.min, "max": self.max,
                "step": self.step, "default": self.default}


@dataclass(frozen=True)
class SourceReading:
    """One reading of a tab list file: the rows in their order, the figures of each row by name, the size of the context
    window (None when the file does not say a positive whole number), the settings fields, and the lines about what was
    left out."""
    rows: tuple[SourceRow, ...]
    figures: dict[str, SourceFigures]
    context_window: int | None
    settings_fields: tuple[SettingsField, ...]
    problems: list[str] = field(default_factory=list)


def _is_number(raw: object) -> bool:
    return isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(raw)


def _context_window(raw: object) -> int | None:
    return raw if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0 else None


def _context_tokens(raw: object) -> int | None:
    return raw if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0 else None


def _spend(raw: object) -> Spend | None:
    """The row's spend, None when it has none or it is not the shape of a spend file."""
    if not isinstance(raw, dict):
        return None
    try:
        return parse_spend(json.dumps(raw))
    except ValueError:
        return None


def _row(raw: object, number: int) -> tuple[SourceRow, SourceFigures] | str:
    """The row as (identity, figures), or the reason it is left out. Only a bad name or record leaves the row out; a
    figure of the wrong type counts as no figure, and a title that is not a text as the name."""
    if not isinstance(raw, dict):
        return f"row {number} skipped: not an object"
    name, title, record = raw.get("name"), raw.get("title"), raw.get("record")
    if not (isinstance(name, str) and ROW_NAME_RE.fullmatch(name)):
        return f"row {number} skipped: the name must match {ROW_NAME_RE.pattern}"
    if not (isinstance(record, str) and Path(record).expanduser().is_absolute()):
        return f"row {number} skipped: {name}: record must be an absolute path"
    identity = SourceRow(name=name, title=title if isinstance(title, str) and title.strip() else name,
                         record=Path(record).expanduser())
    return identity, SourceFigures(context_tokens=_context_tokens(raw.get("context_tokens")), spend=_spend(raw.get("spend")))


def _settings_field(raw: object, number: int) -> SettingsField | str:
    """The field, or the reason it is left out."""
    if not isinstance(raw, dict):
        return f"settings field {number} skipped: not an object"
    key, label, unit = raw.get("key"), raw.get("label"), raw.get("unit")
    low, high, step, default = raw.get("min"), raw.get("max"), raw.get("step"), raw.get("default")
    if not (isinstance(key, str) and FIELD_KEY_RE.fullmatch(key)):
        return f"settings field {number} skipped: the key must match {FIELD_KEY_RE.pattern}"
    if not (isinstance(label, str) and label.strip()):
        return f"settings field {number} skipped: {key}: label must be a text"
    if not all(_is_number(value) for value in (low, high, default)) or not low <= default <= high:
        return f"settings field {number} skipped: {key}: min, max and default must be numbers with min <= default <= max"
    if step is not None and not (_is_number(step) and step > 0):
        return f"settings field {number} skipped: {key}: step must be a positive number"
    return SettingsField(key=key, label=label, unit=unit if isinstance(unit, str) and unit else None,
                         min=low, max=high, step=step, default=default)


def _settings_fields(raw: object, problems: list[str]) -> tuple[SettingsField, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        problems.append("settings_fields skipped: must be a list")
        return ()
    fields: list[SettingsField] = []
    seen: set[str] = set()
    for number, entry in enumerate(raw, start=1):
        found = _settings_field(entry, number)
        if isinstance(found, str):
            problems.append(found)
        elif found.key in seen:
            problems.append(f"settings field {number} skipped: {found.key}: the key is listed twice")
        else:
            seen.add(found.key)
            fields.append(found)
    return tuple(fields)


def parse_source_file(text: str) -> SourceReading:
    """The reading a tab list file's text holds. A row or a field that is not valid is left out with a line in
    `problems` (the rest stay); raises `ValueError` (with the reason) when the text is not a tab list file at all."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"not JSON: {error.msg}") from error
    if not isinstance(raw, dict):
        raise ValueError("not an object")
    tabs = raw.get("tabs")
    if not isinstance(tabs, list):
        raise ValueError("tabs must be a list")
    problems: list[str] = []
    rows: list[SourceRow] = []
    figures: dict[str, SourceFigures] = {}
    for number, entry in enumerate(tabs, start=1):
        found = _row(entry, number)
        if isinstance(found, str):
            problems.append(found)
        elif found[0].name in figures:
            problems.append(f"row {number} skipped: {found[0].name}: the name is listed twice")
        else:
            rows.append(found[0])
            figures[found[0].name] = found[1]
    return SourceReading(rows=tuple(rows), figures=figures, context_window=_context_window(raw.get("context_window")),
                         settings_fields=_settings_fields(raw.get("settings_fields"), problems), problems=problems)
