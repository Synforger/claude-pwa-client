"""The environment a tab starts with: the backend's own, less the Python environment the backend runs in.

Called by `runner` for the process it spawns and for the tmux server's global environment. The backend runs
under `uv run`, which points `VIRTUAL_ENV` and the head of `PATH` at its own environment. A tab that inherited
them would run another repository's `uv run` against the backend's environment and rebuild it for that
repository, taking the backend's dependencies away while it runs.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

#: Variables that name the Python environment the backend itself runs in
PYTHON_ENVIRONMENT_VARIABLES = ("VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT", "UV_PROJECT_ENVIRONMENT", "UV_RUN_RECURSION_DEPTH")
#: Variables whose value is a folder holding a Python environment (= its `bin` is put on `PATH`)
ENVIRONMENT_FOLDERS = ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")


def tab_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """The variables a tab is given: `environ` without the backend's Python environment and its folders on `PATH`."""
    folders = [os.path.realpath(environ[name]) for name in ENVIRONMENT_FOLDERS if environ.get(name)]
    kept = {name: value for name, value in environ.items() if name not in PYTHON_ENVIRONMENT_VARIABLES}
    if "PATH" in kept:
        kept["PATH"] = os.pathsep.join(entry for entry in kept["PATH"].split(os.pathsep)
                                       if not any(_inside(entry, folder) for folder in folders))
    return kept


def read_environment(listed: str) -> dict[str, str]:
    """The variables `tmux show-environment` lists (= `NAME=value` lines; a `-NAME` line is a variable removed)."""
    found = {}
    for line in listed.splitlines():
        name, equals, value = line.partition("=")
        if equals and not name.startswith("-"):
            found[name] = value
    return found


def _inside(entry: str, folder: str) -> bool:
    """Whether a `PATH` entry is the folder or lies under it."""
    if not entry:
        return False
    real = os.path.realpath(entry)
    return real == folder or real.startswith(folder + os.sep)
