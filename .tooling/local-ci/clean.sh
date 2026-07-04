#!/usr/bin/env bash
# =============================================================================
# personal-template / per-layer clean driver
# =============================================================================
# Removes build artefacts / caches / dist outputs per language layer. Hard-coded
# delete lists (= no globs that can escape repo root). Failures are loud; the
# `set -euo pipefail` + `shopt -s nullglob` combo ensures missing dirs do not
# accidentally pass empty paths to `rm -rf`.
#
# Usage:
#   task clean LAYER=python|node|docs|all
#   # or directly:
#   bash .tooling/local-ci/clean.sh <layer>
#
# Exit:
#   0 = success (or layer skipped because nothing existed)
#   1 = unknown layer
# =============================================================================

set -euo pipefail
shopt -s nullglob

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "${SCRIPT_DIR}" in
    */_core/.tooling/local-ci) PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)" ;;
    *)                         PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"   ;;
esac
cd "${PROJECT_ROOT}"

# shellcheck source=setup-lib.sh
source "${SCRIPT_DIR}/setup-lib.sh"

LAYER="${1:-${LAYER:-}}"
if [ -z "${LAYER}" ]; then
    log_fail "usage: clean.sh <layer>  where layer ∈ python|node|docs|all"
    exit 1
fi

# Remove a path (file or dir). No-op on missing.
clean_path() {
    local p
    for p in "$@"; do
        if [ -e "${p}" ] || [ -L "${p}" ]; then
            rm -rf "${p}"
            log_ok "removed ${p}"
        fi
    done
}

clean_python() {
    log_info "cleaning python layer"
    clean_path __pycache__ .pytest_cache .mypy_cache .ruff_cache .coverage \
               htmlcov build dist *.egg-info src/*/__pycache__ \
               src/*/*/__pycache__ tests/__pycache__
    # Recursively delete __pycache__ (= they appear in arbitrary subdirs).
    find . -type d -name __pycache__ \
        -not -path './.venv/*' -not -path './venv/*' \
        -not -path './node_modules/*' -exec rm -rf {} + 2>/dev/null || true
    # Walking pyc files separately catches stray bytecode outside a __pycache__.
    find . -type f -name '*.pyc' \
        -not -path './.venv/*' -not -path './venv/*' \
        -not -path './node_modules/*' -delete 2>/dev/null || true
}

clean_node() {
    log_info "cleaning node layer"
    clean_path node_modules dist .next .vite .turbo .cache \
               frontend/node_modules frontend/dist frontend/.vite
}

clean_docs() {
    log_info "cleaning docs layer"
    clean_path docs/build docs/source/_build site _site
}

case "${LAYER}" in
    python) clean_python ;;
    node)   clean_node ;;
    docs)   clean_docs ;;
    all)
        clean_python
        clean_node
        clean_docs
        ;;
    *)
        log_fail "unknown layer: ${LAYER} (expected: python|node|docs|all)"
        exit 1
        ;;
esac

log_ok "clean.sh ${LAYER}: done"
