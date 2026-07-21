#!/bin/bash
set -euo pipefail

# =============================================================================
# Local Dev Platform - Docs Convention Checker (local)
# =============================================================================
# Scans all tracked Markdown files for template-specific claims that go
# stale when the repo moves, and fails when a claim no longer matches
# reality.
#
# What it checks (the template-specific staleness classes):
#   B. `task <name>` references                        -> task must be listed
#   C. ASCII tree diagrams inside fenced code blocks   -> entries must exist
#      (a tree block is only verified when its root line resolves to an
#       existing directory; trees describing planned/future layouts are
#       skipped automatically because their root does not exist yet)
#   G. git conflict markers (= ^<<<<<<<, ^>>>>>>>) anywhere in a tracked
#      .md, including inside fenced code blocks. Squash-merge mishaps tend
#      to leave these in docs and they go unnoticed for ages. =======
#      is intentionally NOT scanned because it overlaps with markdown h1
#      underlines and would false-positive.
#
# Inline path references (`src/foo/bar.py` -> file must exist) are NOT
# checked here: staledocs owns path/anchor liveness via `task docs:coherence`
# (single source of truth; keeping a second checker produced split verdicts
# and two ignore lists for the same claim). This script keeps only the
# classes staledocs deliberately does not cover because they are template
# conventions, not language-agnostic doc/code drift: Taskfile verb names,
# ASCII layout trees, and merge-mishap fingerprints.
#
# What it cannot check: prose claims about behaviour. Those are covered by
# the review pass before integration, not by this script.
#
# False-positive escape hatch: add one substring or glob per line to
# `docs-check-ignore.txt` (next to this script). Any flagged reference whose
# path matches an ignore line is suppressed. Comments (#) and blanks allowed.
#
# Called from:
#   - `task docs:check`  (= the pre-integration docs sweep entry point)
# Deliberately NOT part of `task lint`: docs are reconciled once before
# integration, not on every dev-loop lint run.
#
# Exit code:
#   0 = clean
#   1 = stale reference found
#   2 = environment error (python3 missing)
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Resolve the repo root regardless of whether this script lives at
# `.tooling/local-ci/` (post-init layout) or `_core/.tooling/local-ci/`
# (template-state layout, before `task init` promotes _core to root).
case "${SCRIPT_DIR}" in
    */_core/.tooling/local-ci) PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)" ;;
    *)                         PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"   ;;
esac
cd "${PROJECT_ROOT}"

if ! command -v python3 >/dev/null 2>&1; then
    echo "error: python3 not found; docs-check requires it" >&2
    exit 2
fi

# Task names are resolved against `task --list-all` when the task binary is
# available; otherwise check B is skipped with a warning.
TASK_NAMES=""
if command -v task >/dev/null 2>&1; then
    TASK_NAMES="$(task --list-all --silent 2>/dev/null || true)"
    # Template state: collect names from staging Taskfiles as well, so docs
    # written against the post-init layout do not fire spurious "unknown
    # task" hits when this script runs from the template root.
    for tf in _core/Taskfile.yml Taskfile.local.yml; do
        [ -f "$tf" ] || continue
        more_names="$(task --list-all --silent --taskfile "$tf" 2>/dev/null || true)"
        if [ -n "${more_names}" ]; then
            TASK_NAMES="${TASK_NAMES}"$'\n'"${more_names}"
        fi
    done
else
    echo "warning: task binary not found; task-name check skipped" >&2
fi
export TASK_NAMES

python3 - "$@" <<'PYEOF'
import os, re, sys, fnmatch

ROOT = os.getcwd()
EXCLUDE_DIRS = {".git", "node_modules", "dist", "build", ".venv", "venv",
                "__pycache__", ".next", ".tooling",
                # Template staging dirs: contents are scanned only after
                # `task init` promotes them to the repo root.
                "_core"}
# Look for the ignore file in either the post-init layout (.tooling/local-ci/)
# or the template-state layout (_core/.tooling/local-ci/).
IGNORE_FILE = os.path.join(ROOT, ".tooling", "local-ci", "docs-check-ignore.txt")
if not os.path.isfile(IGNORE_FILE):
    IGNORE_FILE = os.path.join(ROOT, "_core", ".tooling", "local-ci",
                               "docs-check-ignore.txt")

ignores = []
if os.path.isfile(IGNORE_FILE):
    with open(IGNORE_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line:
                ignores.append(line)

def is_ignored(path):
    return any(fnmatch.fnmatch(path, pat) or pat in path for pat in ignores)

def md_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            if fn.endswith(".md"):
                yield os.path.join(dirpath, fn)

# Tree roots may be a single segment ("docs/"), unlike inline references.
ROOTISH = re.compile(r"^[A-Za-z0-9_.@-]+(/[A-Za-z0-9_.@-]+)*/$")

TREE_CHARS = ("├", "└", "│")
PLACEHOLDER = re.compile(r"[<>{}*$]|\.\.\.|…")
# Conflict-marker shapes that mdoc never legitimately contains. We deliberately
# skip `=======` because that pattern overlaps with markdown h1 underlines, but
# `<<<<<<<` and `>>>>>>>` are unambiguous merge mishap fingerprints.
CONFLICT_RE = re.compile(r"^(<{7}|>{7})( .*)?$")

task_names = set(filter(None, os.environ.get("TASK_NAMES", "").splitlines()))
findings = []

for md in md_files():
    rel_md = os.path.relpath(md, ROOT)
    with open(md, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()

    in_fence = False
    fence_block = []          # (lineno, text) of current fenced block
    for lineno, line in enumerate(lines, 1):
        # ---- check G: git conflict markers (= squash/merge mishap) ----
        # Run before fence handling so markers inside code blocks also fire.
        if CONFLICT_RE.match(line):
            if not is_ignored(line.strip()):
                findings.append(
                    f"{rel_md}:{lineno}: git conflict marker: "
                    f"{line[:40]}")
            continue
        if line.lstrip().startswith("```"):
            if in_fence:
                # ---- check C: tree diagrams in the closed block ----
                block = fence_block
                tree_idx = [i for i, (_, t) in enumerate(block)
                            if any(c in t for c in TREE_CHARS)]
                if tree_idx:
                    # root = nearest line above the first tree line that is
                    # a bare "dir/" path resolving to a real directory
                    root_dir = None
                    for i in range(tree_idx[0] - 1, -1, -1):
                        cand = block[i][1].strip()
                        if ROOTISH.match(cand):
                            if os.path.isdir(os.path.join(ROOT, cand)):
                                root_dir = cand
                            break
                    if root_dir:
                        stack = []  # (depth, name)
                        for i in tree_idx:
                            ln, text = block[i]
                            m = re.search(r"[├└]─* ?(.+)$", text)
                            if not m:
                                continue
                            depth = m.start()  # column of the branch char
                            # composite lines list siblings on one line
                            # ("A / B / C" or "A + B"); drop the trailing
                            # `#` comment and split on the separators.
                            # Only treat the line as composite when every
                            # segment is a single token — a multi-word
                            # segment means free-text annotation (e.g.
                            # "← ..." commentary), where splitting would
                            # turn prose into bogus entries; fall back to
                            # the first token only.
                            entry = m.group(1).split("#", 1)[0]
                            segs = [seg.split()
                                    for seg in re.split(r"\s+[/+]\s+", entry)
                                    if seg.split()]
                            if all(len(s) == 1 for s in segs):
                                names = [s[0] for s in segs]
                            else:
                                names = [segs[0][0]] if segs else []
                            names = [n for n in names
                                     if not PLACEHOLDER.search(n)]
                            if not names:
                                continue
                            # first name carries the tree structure
                            stack = [(d, n) for d, n in stack if d < depth]
                            stack.append((depth, names[0].rstrip("/")))
                            parent = [n for _, n in stack[:-1]]
                            for name in names:
                                full = os.path.join(root_dir, *parent,
                                                    name.rstrip("/"))
                                if not os.path.exists(
                                        os.path.join(ROOT, full)):
                                    if not is_ignored(full):
                                        findings.append(
                                            f"{rel_md}:{ln}: tree entry"
                                            f" not found: {full}")
                fence_block = []
                in_fence = False
            else:
                in_fence = True
            continue
        if in_fence:
            fence_block.append((lineno, line))
            continue

        # ---- check B: `task xxx` references ----
        for span in re.findall(r"`([^`\n]+)`", line):
            span = span.strip()
            if PLACEHOLDER.search(span):
                continue
            m = re.match(r"^task\s+([A-Za-z0-9][A-Za-z0-9:_-]*)$", span)
            if m and task_names and m.group(1) not in task_names:
                if not is_ignored(span):
                    findings.append(
                        f"{rel_md}:{lineno}: unknown task: {span}")

if findings:
    print("\n".join(findings))
    print(f"\ndocs-check: {len(findings)} stale reference(s)."
          " Fix the doc or add an exception to"
          " .tooling/local-ci/docs-check-ignore.txt")
    sys.exit(1)
print("docs-check: clean")
PYEOF
