"""The table of paths that `/file` never reads or writes, and the one function that matches it.

A path is matched twice with the same table: by its spelling, and by the name the file system itself reports for it.
Both are normalised the same way before matching.

Used by `backend/routes/files.py` (every route resolves its path through it) and
`backend/routes/debug_healthcheck.py`.
"""
from __future__ import annotations

import fcntl
import os
import re
import unicodedata
from pathlib import Path

# macOS opens a file for events only, without reading it and without waiting on a device.
_O_EVTONLY = 0x8000
_PATH_BUFFER_BYTES = 1024

# The names are matched by name and not by place: a file that holds a token sits in a repo or an app as often as in the
# home folder. Order: keys and credentials, then settings that hold a token in plain text, then shell start-up files.
# A template such as `.env.example` holds a sample, so it passes.
_DENY_RE = re.compile(
    r"(?:^|/)(?:"
    r"\.ssh|\.aws|\.gnupg|\.kube|\.docker|\.azure|\.config/gh|\.config/gcloud|Library/Keychains|"
    r"\.netrc|\.npmrc|\.pypirc|\.git-credentials|\.pgpass|"
    r"\.envrc|\.credentials\.json|\.claude\.json|secrets|"
    r"\.zshrc|\.zshenv|\.zprofile|\.bashrc|\.bash_profile|\.profile|"
    r"\.zsh_history|\.bash_history"
    r")(?:$|/)"
    r"|(?:^|/)\.env(?:\.(?!(?:example|sample|template)$)[^/]*)?$"
    r"|(?:^|/)(?:authorized_keys|id_rsa|id_ed25519|id_ecdsa|id_dsa|known_hosts)$"
    r"|\.(?:pem|key|p12|pfx)$",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", text).casefold())


def _name_of_entry(path: Path, get_path: int) -> str:
    """The file system's own name for an entry that exists. Raises `OSError` when it cannot be opened."""
    descriptor = os.open(path, _O_EVTONLY | os.O_NONBLOCK)
    try:
        raw = fcntl.fcntl(descriptor, get_path, b"\0" * _PATH_BUFFER_BYTES)
    finally:
        os.close(descriptor)
    return os.fsdecode(raw.split(b"\0", 1)[0])


def _filesystem_name(path: Path) -> str | None:
    """The path with its longest existing part replaced by the file system's own name for it.

    `None` when the platform cannot tell, or when a part exists but cannot be opened (a part that cannot be opened
    cannot be read either, so the spelling alone decides).
    """
    get_path = getattr(fcntl, "F_GETPATH", None)
    if get_path is None:
        return None
    missing: list[str] = []
    for ancestor in (path, *path.parents):
        try:
            return str(Path(_name_of_entry(ancestor, get_path), *reversed(missing)))
        except (FileNotFoundError, NotADirectoryError):
            missing.append(ancestor.name)
        except OSError:
            return None
    return None


def is_denied(path: Path) -> bool:
    """Whether `/file` must refuse this resolved path, by its spelling or by the file system's name for it."""
    if _DENY_RE.search(_normalize(str(path))):
        return True
    reported = _filesystem_name(path)
    return reported is not None and bool(_DENY_RE.search(_normalize(reported)))
