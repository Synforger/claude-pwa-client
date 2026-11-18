"""What the settings screen may write into a program's settings file, judged against the fields the program declared
(`api_tab_source_file.SettingsField`), and what the screen shows as each field's value.

Pure: the fields, the values and the file's object come in, the reasons or the new object go out; no file is touched.
Used by `api_source_settings.py`.
"""
from __future__ import annotations

import math

from backend.api_tabs.api_tab_source_file import SettingsField

#: How far a value may sit from the grid of `step` and still be on it (= what a decimal step written in JSON loses).
STEP_TOLERANCE = 1e-9


def _is_number(raw: object) -> bool:
    return isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(raw)


def _on_grid(value: float, settings_field: SettingsField) -> bool:
    if settings_field.step is None:
        return True
    steps = (value - settings_field.min) / settings_field.step
    return abs(steps - round(steps)) <= STEP_TOLERANCE * max(1.0, abs(steps))


def rejections(fields: tuple[SettingsField, ...], values: object) -> list[str]:
    """Why `values` (= `{key: number}` from the screen) may not be written; empty when every value may."""
    if not isinstance(values, dict) or not values:
        return ["values must be an object with at least one field"]
    by_key = {settings_field.key: settings_field for settings_field in fields}
    reasons: list[str] = []
    for key, value in values.items():
        settings_field = by_key.get(key)
        if settings_field is None:
            reasons.append(f"{key}: the program declares no such field")
        elif not _is_number(value):
            reasons.append(f"{key}: must be a number")
        elif not settings_field.min <= value <= settings_field.max:
            reasons.append(f"{key}: must be between {settings_field.min} and {settings_field.max}")
        elif not _on_grid(value, settings_field):
            reasons.append(f"{key}: must be {settings_field.min} plus a whole number of {settings_field.step}")
    return reasons


def _is_whole(settings_field: SettingsField) -> bool:
    """Whether the field takes whole numbers only: its grid starts at a whole number and steps by one."""
    return settings_field.step is not None and float(settings_field.step).is_integer() and float(settings_field.min).is_integer()


def with_values(written: dict, fields: tuple[SettingsField, ...], values: dict) -> dict:
    """The settings file's object with `values` (already judged by `rejections`) put in: the keys it had keep their
    place and the keys it did not have come last; every other key is kept as it was. A field of whole numbers is written
    as a whole number (`5`, never `5.0`)."""
    by_key = {settings_field.key: settings_field for settings_field in fields}
    put = {key: int(round(value)) if _is_whole(by_key[key]) else value for key, value in values.items()}
    return {**written, **put}


def shown_values(fields: tuple[SettingsField, ...], written: dict | None) -> dict:
    """The value of each field as the screen shows it: the file's own when it is a number, the field's default otherwise
    (= what the program uses then)."""
    written = written or {}
    return {settings_field.key: written[settings_field.key] if _is_number(written.get(settings_field.key))
            else settings_field.default for settings_field in fields}
