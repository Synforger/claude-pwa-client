"""The table of paths that `/file` never reads or writes, the table of those it only reads, and how they are matched.

A path is matched twice with each table: by its spelling, and by the name the file system itself reports for it.
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
# home folder. A listed name stands for the names made from it too: with a separator and more behind it, or with a
# separator before it. A template such as `.env.example` holds a sample, so it passes.
_AND_MORE = r"(?:[._~-](?!(?:example|sample|template)$)[^/]*)?"
# An ending that marks an earlier state of a file, for the names too common to take every ending.
_EARLIER = r"(?:~|\.\d+|[._~-](?:bak|backup|old|orig|original|save|saved|tmp|copy|before|prev|swp)(?:[0-9._~-][^/]*)?)"
_DATA_FORMAT = r"(?:\.(?:json|toml|ya?ml|ini|cfg|conf|env|txt|csv|xml|enc|plist))"

_LISTED_NAMES = (
    # keys and credentials, and the settings that hold a token in plain text
    r"(?:\.ssh|\.aws|\.gnupg|\.kube|\.docker|\.azure|\.config/gh|\.config/gcloud|Library/Keychains)" + _AND_MORE,
    r"(?:\.netrc|\.npmrc|\.pypirc|\.git-credentials|\.pgpass|\.credentials\.json|\.env)" + _AND_MORE,
    r"(?:[^/]*[._~-])?claude\.json" + _AND_MORE,
    r"env" + _EARLIER,
    r"[^a-z0-9/]*secrets[^a-z0-9/]*" + _DATA_FORMAT + "?" + _EARLIER + "?",
    # a package may have a folder of this name, so the plain word stands for a file only
    r"[^a-z0-9/]*credentials(?:" + _DATA_FORMAT + _EARLIER + "?|" + _EARLIER + "|$)",
    r"(?:authorized_keys|known_hosts|id_rsa|id_ed25519|id_ecdsa|id_dsa)"
    r"(?:[._~-](?!(?:pub|example|sample|template)$)[^/]*)?",
    # shell start-up files and histories
    r"(?:\.profile|\.zsh_history|\.bash_history)" + _AND_MORE,
    r"(?:[^/]*[._~-])?(?:zshrc|zshenv|zprofile|bashrc|bash_profile|envrc)" + _AND_MORE,
    # the folders where Claude Code and its records keep earlier states
    r"\.claude[^/]*/backups",
    r"\.claude-backup[^/]*",
)
_DENY_RE = re.compile(
    r"(?:^|/)(?:" + "|".join(_LISTED_NAMES) + r")(?:$|/)"
    r"|\.(?:pem|key|p12|pfx)" + _EARLIER + "?$",
    re.IGNORECASE,
)

# Read as any file and never written: the screen's editor opens none of them. A name with no extension counts, but for
# those the editor knows by the whole name (`FilePreviewModal.jsx`).
_NO_EXTENSION = (
    r"(?!(?:dockerfile|containerfile|makefile|gnumakefile|cmakelists|rakefile|gemfile|procfile)$)"
    r"[^/.]+(?:\.\d+)*"
)
_READ_ONLY_NAMES = (
    r"\.(?:zlogin|zlogout|bash_login|bash_logout|login|logout|cshrc|tcshrc|xonshrc)(?:\.zwc)?",
    r"\.config/xonsh/rc\.xsh",
    r"Library/LaunchAgents/[^/]+\.plist",
    r"(?:[^/]*\.git(?:/modules(?:/[^/]+){1,8})?|\.config/git|\.claude[^/]*)/hooks/(?:[^/]+/)*" + _NO_EXTENSION,
    r"(?:\.githooks|\.git-hooks|\.husky)/(?:[^/]+/)*" + _NO_EXTENSION,
    r"(?:\.?bin|sbin|condabin|shims)/" + _NO_EXTENSION,
)
_READ_ONLY_RE = re.compile(r"(?:^|/)(?:" + "|".join(_READ_ONLY_NAMES) + r")$", re.IGNORECASE)


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
    return _matches(path, _DENY_RE)


def is_write_denied(path: Path) -> bool:
    """Whether `/file` must refuse to write this resolved path: what it refuses altogether, and what it only reads."""
    return _matches(path, _DENY_RE, _READ_ONLY_RE)


def _matches(path: Path, *tables: re.Pattern[str]) -> bool:
    spelling = _normalize(str(path))
    if any(table.search(spelling) for table in tables):
        return True
    reported = _filesystem_name(path)
    if reported is None:
        return False
    name = _normalize(reported)
    return any(table.search(name) for table in tables)
