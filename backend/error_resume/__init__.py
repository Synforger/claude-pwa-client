"""Telling a tab whose turn a passing API error ended to carry on (see `docs/reference/error-resume.md`).

This file imports nothing on purpose: the child watch reads `error_sensors.py`, and the patrol (`error_patrol.py`) uses
the child watch to tell a parent, so an import here would make the two packages import each other.
"""
