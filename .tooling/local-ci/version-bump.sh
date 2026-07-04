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

try:
    import yaml
except ModuleNotFoundError:
    print("error: PyYAML not installed; run `pip install pyyaml` and retry", file=sys.stderr)
    sys.exit(2)

targets_path = Path(sys.argv[1])
level = sys.argv[2]
dry_run = sys.argv[3] in ("1", "true", "yes")

data = yaml.safe_load(targets_path.read_text())
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
    # Update current_version in the targets file itself. Naive line replacement
    # (assumes 'current_version: "X.Y.Z"' on a single line).
    targets_text = targets_path.read_text()
    targets_text = re.sub(
        r'^(current_version:\s*").*?(")',
        rf'\g<1>{new_version}\g<2>',
        targets_text,
        count=1,
        flags=re.MULTILINE,
    )
    targets_path.write_text(targets_text)
    print(f"updated current_version in {targets_path.name} -> {new_version}")

print(f"done: {total_edits} total edit(s) across {sum(1 for _ in data.get('targets') or [])} target(s)")
PYEOF
