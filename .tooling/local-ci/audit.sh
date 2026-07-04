#!/usr/bin/env bash
# =============================================================================
# personal-template / aggregate security audit
# =============================================================================
# Runs every available security scanner against the working tree and aggregates
# exit codes. Each scanner section is skipped (with a warning, not a fail) when
# the corresponding tool is not on PATH or the stack is absent — keeps
# `task audit` workable with any mix of stacks.
#
# Scanners (= roughly in fastest-to-slowest order):
#   - anon-scan           full-tree personal-identifier scan
#   - gitleaks            full-history secret scan (= deeper than the pre-commit
#                         `gitleaks protect --staged` mode)
#   - pip-audit           python: PyPI advisory db check
#   - npm audit           node: npm advisory db check (production deps)
#
# Usage:
#   task audit
#   # or directly:
#   bash .tooling/local-ci/audit.sh
#
# Exit:
#   0 = every available scanner clean (or skipped)
#   1 = at least one scanner reported findings
# =============================================================================

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "${SCRIPT_DIR}" in
    */_core/.tooling/local-ci) PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)" ;;
    *)                         PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"   ;;
esac
cd "${PROJECT_ROOT}"

# shellcheck source=setup-lib.sh
source "${SCRIPT_DIR}/setup-lib.sh"

overall_fail=0

run_section() {
    local label="$1"; shift
    local title="=== ${label} ==="
    printf '\n%s\n' "${title}" >&2
    if "$@"; then
        log_ok "${label}: clean"
    else
        log_fail "${label}: findings (exit=$?)"
        overall_fail=1
    fi
}

skip_section() {
    local label="$1"; shift
    local reason="$*"
    printf '\n=== %s ===\n' "${label}" >&2
    log_warn "${label}: skipped (${reason})"
}

# ---- anon-scan -------------------------------------------------------------

ANON_SCANNER="${SCRIPT_DIR}/anon-scan.sh"
if [ ! -x "${ANON_SCANNER}" ] && [ -f "${HOME}/.git-hooks/scanners/anon-scan.sh" ]; then
    ANON_SCANNER="${HOME}/.git-hooks/scanners/anon-scan.sh"
fi
if [ -f "${ANON_SCANNER}" ]; then
    run_section "anon-scan" bash "${ANON_SCANNER}"
else
    skip_section "anon-scan" "scanner not found (repo-local or guard-dispatcher)"
fi

# ---- gitleaks (full-history) -----------------------------------------------

if check_command gitleaks; then
    run_section "gitleaks (full history)" gitleaks detect --no-banner --redact
else
    skip_section "gitleaks" "not installed (brew install gitleaks | apt install gitleaks)"
fi

# ---- pip-audit (python) ----------------------------------------------------

# NOTE: every language probe below looks ONLY at the post-init layout
# (= project root or its known sub-dirs like frontend/).

if [ -f "pyproject.toml" ]; then
    if check_command pip-audit; then
        run_section "pip-audit" pip-audit
    elif check_command pip; then
        skip_section "pip-audit" "not installed (pip install pip-audit)"
    else
        skip_section "pip-audit" "neither pip nor pip-audit available"
    fi
else
    skip_section "pip-audit" "python stack not detected (= no pyproject.toml at root)"
fi

# ---- npm audit (node) --------------------------------------------------------

NODE_DIR=""
for c in "${PROJECT_ROOT}" "${PROJECT_ROOT}/frontend"; do
    if [ -f "${c}/package.json" ]; then NODE_DIR="${c}"; break; fi
done
if [ -n "${NODE_DIR}" ]; then
    if check_command npm; then
        run_section "npm audit (${NODE_DIR#${PROJECT_ROOT}/})" \
            bash -c "cd '${NODE_DIR}' && npm audit --omit=dev"
    else
        skip_section "npm audit" "npm not installed"
    fi
else
    skip_section "npm audit" "node stack not detected (= no package.json at root)"
fi


printf '\n' >&2
if [ "${overall_fail}" -eq 0 ]; then
    log_ok "audit: all available scanners clean"
    exit 0
fi
log_fail "audit: one or more scanners reported findings"
exit 1
