#!/usr/bin/env bash
# =============================================================================
# personal-template / release driver
# =============================================================================
# Bumps the version, commits the rewrite, tags it, and (optionally) pushes.
#
# Usage:
#   task release:cut LEVEL=patch|minor|major  [DRY_RUN=1] [SKIP_PUSH=1]
#   # or directly:
#   LEVEL=patch bash .tooling/local-ci/release-cut.sh
#
# Env knobs:
#   DRY_RUN=1      Print the plan, do not modify files / commit / tag / push.
#   SKIP_PUSH=1    Bump + commit + tag, but do not push (= for review).
#
# Exit codes:
#   0  Success.
#   1  Working tree not clean (= refuse to bump on top of unfinished work).
#   2  Bad arguments or env error.
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
SKIP_PUSH="${SKIP_PUSH:-0}"

case "${LEVEL}" in
    major|minor|patch) ;;
    *) log_fail "LEVEL must be one of: major|minor|patch (got '${LEVEL}')"; exit 2 ;;
esac

# Refuse to cut on top of uncommitted work — release commits should be clean.
if [ -n "$(git status --porcelain)" ] && [ "${DRY_RUN}" != "1" ]; then
    log_fail "working tree not clean; commit or stash before cutting a release"
    git status --short
    exit 1
fi

# Bump (= delegates to version-bump.sh, honours DRY_RUN).
LEVEL="${LEVEL}" DRY_RUN="${DRY_RUN}" bash "${SCRIPT_DIR}/version-bump.sh"

if [ "${DRY_RUN}" = "1" ]; then
    log_info "DRY_RUN=1 → skipping git commit / tag / push"
    exit 0
fi

# Read the just-updated version back from bump-targets.yaml.
TARGETS_FILE=".tooling/bump-targets.yaml"
[ -f "${TARGETS_FILE}" ] || TARGETS_FILE="_core/.tooling/bump-targets.yaml"
NEW_VERSION="$(sed -nE 's/^current_version:[[:space:]]*"([^"]+)".*/\1/p' "${TARGETS_FILE}" | head -1)"

if [ -z "${NEW_VERSION}" ]; then
    log_fail "could not read new version from ${TARGETS_FILE}"
    exit 2
fi

log_info "committing release v${NEW_VERSION}"
git add -A
git commit -m "chore: release v${NEW_VERSION}"
git tag -a "v${NEW_VERSION}" -m "Release v${NEW_VERSION}"

if [ "${SKIP_PUSH}" = "1" ]; then
    log_ok "v${NEW_VERSION} committed + tagged locally; SKIP_PUSH=1, not pushing"
    log_info "push manually with: git push && git push --tags"
    exit 0
fi

log_info "pushing branch + tag"
git push
git push origin "v${NEW_VERSION}"
log_ok "release v${NEW_VERSION} cut + pushed"
