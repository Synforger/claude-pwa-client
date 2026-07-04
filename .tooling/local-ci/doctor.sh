#!/usr/bin/env bash
# =============================================================================
# personal-template / preflight doctor
# =============================================================================
# Walks every entry in .tooling/versions.yaml, checks the binary in PATH,
# reports MISSING / TOO OLD / OK with install hints, and exits 0 if all
# entries pass, 1 if any fail.
#
# Called from:
#   - `task doctor`  (= manual preflight)
#   - Recommended before `task setup` on a new machine.
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

# install hints (= one-line shell suggestion per tool, used only when MISSING).
install_hint() {
    case "$1" in
        bash)   echo "brew install bash  # macOS already ships 3.x, /opt/homebrew/bin/bash for 5.x" ;;
        git)    echo "brew install git | apt install git" ;;
        python) echo "brew install python@3.12 | apt install python3" ;;
        node)   echo "brew install node | nvm install --lts" ;;
        jq)     echo "brew install jq | apt install jq" ;;
        *)      echo "(no install hint for $1)" ;;
    esac
}

fail_count=0
ok_count=0

# Iterate over VERSION_* env vars set by load_versions.
for env_var in $(compgen -e | grep '^VERSION_' | sort); do
    key_upper="${env_var#VERSION_}"
    key="$(printf '%s' "${key_upper}" | tr '[:upper:]' '[:lower:]')"
    constraint="${!env_var}"
    bin="$(binary_name "${key}")"

    if ! check_command "${bin}"; then
        log_fail "$(printf '%-8s MISSING  (want %s, try: %s)' "${key}" "${constraint}" "$(install_hint "${key}")")"
        fail_count=$((fail_count + 1))
        continue
    fi

    actual="$(get_version "${key}")"
    if [ -z "${actual}" ]; then
        log_warn "$(printf '%-8s INSTALLED but version probe failed (binary=%s, want %s)' "${key}" "${bin}" "${constraint}")"
        fail_count=$((fail_count + 1))
        continue
    fi

    if version_satisfies "${actual}" "${constraint}"; then
        log_ok "$(printf '%-8s %-10s (need %s)' "${key}" "${actual}" "${constraint}")"
        ok_count=$((ok_count + 1))
    else
        log_fail "$(printf '%-8s TOO OLD  (have %s, need %s, try: %s)' "${key}" "${actual}" "${constraint}" "$(install_hint "${key}")")"
        fail_count=$((fail_count + 1))
    fi
done

echo "" >&2
log_info "doctor summary: ${ok_count} ok, ${fail_count} fail"
exit "${fail_count}"
