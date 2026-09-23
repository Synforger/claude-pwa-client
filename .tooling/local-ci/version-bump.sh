#!/usr/bin/env bash
# =============================================================================
# personal-template / version bumper
# =============================================================================
# Bumps the project version recorded in `.tooling/bump-targets.yaml`, rewrites
# every listed target file with the new version, and updates the truth in the
# same file. Does NOT commit / tag / push — that's `release-cut.sh`.
#
# Usage:
#   task version:bump LEVEL=patch|minor|major  [DRY_RUN=1]
#   # or directly:
#   LEVEL=patch bash .tooling/local-ci/version-bump.sh
#
# DRY_RUN=1 prints the plan (= old/new versions, target files, edit counts)
# without touching the filesystem.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "${SCRIPT_DIR}" in
    */_core/.tooling/local-ci) PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)" ;;
    *)                         PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"   ;;
esac
cd "${PROJECT_ROOT}"

# shellcheck source=setup-lib.sh
source "${SCRIPT_DIR}/setup-lib.sh"

LEVEL="${LEVEL:-patch}"
DRY_RUN="${DRY_RUN:-0}"

case "${LEVEL}" in
    major|minor|patch) ;;
    *) log_fail "LEVEL must be one of: major|minor|patch (got '${LEVEL}')"; exit 2 ;;
esac

if [ ! -f ".tooling/bump-targets.yaml" ] && [ ! -f "_core/.tooling/bump-targets.yaml" ]; then
    log_fail "bump-targets.yaml not found (looked in .tooling/ and _core/.tooling/)"
    exit 2
fi

TARGETS_FILE=".tooling/bump-targets.yaml"
[ -f "${TARGETS_FILE}" ] || TARGETS_FILE="_core/.tooling/bump-targets.yaml"

# Python helper does parse + arithmetic + apply (keeping the bash side minimal).
python3 - "${TARGETS_FILE}" "${LEVEL}" "${DRY_RUN}" <<'PYEOF'
import re
import sys
from pathlib import Path


def _scalar(value):
    """One value, with surrounding quotes or a trailing comment removed."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value.split(" #", 1)[0].rstrip()


def read_targets(path):
    """Read bump-targets.yaml without a YAML library.

    The file is a fixed, small shape - current_version plus a list of files
    with literal search/replace pairs - so it is read directly rather than
    pulling in a dependency the rest of this tooling does not have. Anything
    the reader does not recognise raises: dropping a target silently would
    rewrite some files and leave others on the old version.
    """
    data = {"current_version": "", "targets": []}
    entry = None
    rep = None
    in_targets = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        body = raw.strip()
        if indent == 0:
            if body.startswith("current_version:"):
                data["current_version"] = _scalar(body.split(":", 1)[1])
                in_targets = False
            elif body.rstrip() == "targets:":
                in_targets = True
            else:
                raise ValueError("unexpected top-level line: %r" % raw)
            continue
        if not in_targets:
            raise ValueError("unexpected line outside targets: %r" % raw)
        if body.startswith("- file:"):
            entry = {"file": _scalar(body.split(":", 1)[1]), "replacements": []}
            data["targets"].append(entry)
            rep = None
        elif body.rstrip() == "replacements:":
            if entry is None:
                raise ValueError("replacements before any file entry")
        elif body.startswith("- search:"):
            if entry is None:
                raise ValueError("search before any file entry")
            rep = {"search": _scalar(body.split(":", 1)[1])}
            entry["replacements"].append(rep)
        elif body.startswith("replace:"):
            if rep is None:
                raise ValueError("replace without a search")
            rep["replace"] = _scalar(body.split(":", 1)[1])
        else:
            raise ValueError("unexpected line: %r" % raw)
    for one in data["targets"]:
        for pair in one["replacements"]:
            if "replace" not in pair:
                raise ValueError("%s: a search has no replace" % one["file"])
    return data


targets_path = Path(sys.argv[1])
level = sys.argv[2]
dry_run = sys.argv[3] in ("1", "true", "yes")

try:
    data = read_targets(targets_path)
except (OSError, ValueError) as error:
    print("error: cannot read %s: %s" % (targets_path.name, error), file=sys.stderr)
    sys.exit(2)
current = str(data.get("current_version") or "").strip()
m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", current)
if not m:
    print(f"error: current_version '{current}' is not in X.Y.Z form", file=sys.stderr)
    sys.exit(2)

old_major, old_minor, old_patch = (int(x) for x in m.groups())
if level == "major":
    new_major, new_minor, new_patch = old_major + 1, 0, 0
elif level == "minor":
    new_major, new_minor, new_patch = old_major, old_minor + 1, 0
else:  # patch
    new_major, new_minor, new_patch = old_major, old_minor, old_patch + 1

old_version = f"{old_major}.{old_minor}.{old_patch}"
new_version = f"{new_major}.{new_minor}.{new_patch}"

vars_map = {
    "OLD": old_version,
    "NEW": new_version,
    "OLD_MAJOR": str(old_major),
    "OLD_MINOR": str(old_minor),
    "OLD_PATCH": str(old_patch),
    "NEW_MAJOR": str(new_major),
    "NEW_MINOR": str(new_minor),
    "NEW_PATCH": str(new_patch),
}

def expand(s: str) -> str:
    out = s
    for k, v in vars_map.items():
        out = out.replace("{" + k + "}", v)
    return out

print(f"version-bump: {old_version} -> {new_version} (level={level}, dry_run={dry_run})")

repo_root = targets_path.resolve().parent.parent.parent if "_core" in targets_path.parts else targets_path.resolve().parent.parent
total_edits = 0
for entry in data.get("targets") or []:
    file_path = repo_root / entry["file"]
    if not file_path.is_file():
        print(f"  skip: {entry['file']} not found (stack removed?)")
        continue
    text = file_path.read_text()
    edits = 0
    for rep in entry.get("replacements") or []:
        search = expand(rep["search"])
        replace = expand(rep["replace"])
        if search not in text:
            print(f"  warn: {entry['file']}: search literal not found: {search!r}")
            continue
        new_text, n = text.replace(search, replace), text.count(search)
        text = new_text
        edits += n
    if edits == 0:
        print(f"  skip: {entry['file']} (= 0 matching lines)")
        continue
    if dry_run:
        print(f"  plan: {entry['file']} (= {edits} edit(s))")
    else:
        file_path.write_text(text)
        print(f"  wrote: {entry['file']} (= {edits} edit(s))")
    total_edits += edits

if not dry_run:
    # Update current_version in the targets file itself. Accepts both the
    # quoted and unquoted YAML forms (init.py resets it unquoted) and fails
    # loudly instead of pretending when nothing matched.
    targets_text = targets_path.read_text()
    targets_text, n = re.subn(
        r'^(current_version:\s*"?)[0-9]+\.[0-9]+\.[0-9]+("?\s*)$',
        rf'\g<1>{new_version}\g<2>',
        targets_text,
        count=1,
        flags=re.MULTILINE,
    )
    if n != 1:
        print(f"error: could not rewrite current_version in {targets_path.name}", file=sys.stderr)
        sys.exit(1)
    targets_path.write_text(targets_text)
    print(f"updated current_version in {targets_path.name} -> {new_version}")

print(f"done: {total_edits} total edit(s) across {sum(1 for _ in data.get('targets') or [])} target(s)")
PYEOF
