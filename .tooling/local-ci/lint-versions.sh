#!/usr/bin/env bash
# =============================================================================
# personal-template / downstream toolchain drift detector
# =============================================================================
# Walks downstream config files that pin toolchain versions and fails if any
# diverge from .tooling/versions.yaml.
#
# Targets (= add new ones when adopting a stack):
#   - Python   pyproject.toml `requires-python`  vs python
#   - Node     package.json   `engines.node`     vs node
#
# Called from:
#   - `task lint:versions`
#   - Recommended after editing versions.yaml.
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

load_versions

fail_count=0

# Helper: extract a value from a key=value-ish line using a regex.
# Args: <file> <regex> ; prints first capture group.
extract() {
    local file="$1" regex="$2"
    [ -f "${file}" ] || return 1
    sed -nE "${regex}" "${file}" | head -1
}

# Helper: ensure downstream value >= truth's floor.
# Args: <label> <downstream-value> <truth-key>
require_at_least() {
    local label="$1" downstream="$2" truth_key="$3"
    local upper truth
    upper="$(printf '%s' "${truth_key}" | tr '[:lower:]' '[:upper:]')"
    truth="$(eval "echo \${VERSION_${upper}:-}")"
    if [ -z "${truth}" ]; then
        log_warn "${label}: no truth entry for '${truth_key}' in versions.yaml (skip)"
        return 0
    fi
    if [ -z "${downstream}" ]; then
        log_warn "${label}: pin not found (skip)"
        return 0
    fi
    if version_satisfies "${downstream}" "${truth}"; then
        log_ok "${label}: ${downstream} satisfies ${truth}"
    else
        log_fail "${label}: ${downstream} does NOT satisfy ${truth} (update the downstream file or relax the truth)"
        fail_count=$((fail_count + 1))
    fi
}

# ---- Python: pyproject.toml `requires-python` ---------------------

for pp in pyproject.toml; do
    if [ -f "${pp}" ]; then
        py_pin="$(extract "${pp}" 's/^requires-python *= *"[><= ]*([0-9]+\.[0-9]+(\.[0-9]+)?)".*/\1/p')"
        require_at_least "${pp} requires-python" "${py_pin}" "python"
    fi
done

# ---- Node: package.json `engines.node` ----------------------------

for pkg in package.json; do
    if [ -f "${pkg}" ]; then
        # Tolerate "engines": { "node": ">=20" } across multiple lines.
        node_pin="$(python3 -c '
import json, re, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
spec = (data.get("engines") or {}).get("node", "")
m = re.search(r"([0-9]+\.[0-9]+(\.[0-9]+)?)", spec)
print(m.group(1) if m else "")
' "${pkg}" 2>/dev/null || true)"
        require_at_least "${pkg} engines.node" "${node_pin}" "node"
    fi
done



echo "" >&2
if [ "${fail_count}" -eq 0 ]; then
    log_info "lint-versions: clean"
    exit 0
fi
log_fail "lint-versions: ${fail_count} mismatch(es)"
exit 1
