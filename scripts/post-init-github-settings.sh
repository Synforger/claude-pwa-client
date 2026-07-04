#!/usr/bin/env bash
# =============================================================================
# personal-template / post-init GitHub settings
# =============================================================================
# Restores the GitHub repo settings that the "Use this template" flow does
# NOT carry over from the source template (= security toggles, merge config,
# branch protection, deletes-on-merge). Run once after creating a new repo
# from the template, then optionally re-run when settings drift.
#
# Usage:
#   task init:github             # auto-detect owner/repo from git remote
#   task init:github OWNER=Synforger REPO=my-new-repo
#   bash scripts/post-init-github-settings.sh Synforger my-new-repo
#
# Requirements:
#   - gh CLI installed + authenticated as a user with admin rights on the repo
#   - The repo must already exist on GitHub
#
# What this script applies (= the 80% gh api can automate):
#   1. Code security and analysis
#      - secret_scanning            : enabled
#      - secret_scanning_push_protection : enabled
#      - dependabot_security_updates : enabled
#   2. Private Vulnerability Reporting       : enabled
#   3. Merge settings
#      - delete_branch_on_merge   : true
#      - allow_squash_merge       : true
#      - allow_merge_commit       : false
#      - allow_rebase_merge       : true
#      - allow_auto_merge         : false
#   4. Branch protection on main (= delegates to setup-branch-protection.sh)
#
# What this script does NOT apply (= residual 20% that requires UI):
#   - Secret scanning "Non-provider patterns" (= API accepts but stays disabled)
#   - Code scanning (CodeQL) default setup (= UI button only)
#   - Repo visibility / template flag changes
#   - Collaborators / teams / secrets (= per-repo so not template-able)
#
# These manual TODOs are printed at the end with URLs.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Resolve OWNER + REPO from args, env, or `git remote get-url origin`.
OWNER="${1:-${OWNER:-}}"
REPO="${2:-${REPO:-}}"

if [ -z "${OWNER}" ] || [ -z "${REPO}" ]; then
    if command -v git >/dev/null 2>&1 && git -C "${REPO_ROOT}" remote get-url origin >/dev/null 2>&1; then
        remote_url="$(git -C "${REPO_ROOT}" remote get-url origin)"
        # Handles git@github.com:Owner/Repo.git and https://github.com/Owner/Repo(.git)
        match="$(printf '%s' "${remote_url}" | sed -nE 's|.*github\.com[/:]([^/]+)/([^/.]+)(\.git)?$|\1 \2|p')"
        if [ -n "${match}" ]; then
            OWNER="${OWNER:-$(printf '%s' "${match}" | awk '{print $1}')}"
            REPO="${REPO:-$(printf '%s' "${match}" | awk '{print $2}')}"
        fi
    fi
fi

if [ -z "${OWNER}" ] || [ -z "${REPO}" ]; then
    echo "error: could not resolve OWNER/REPO" >&2
    echo "       usage: $0 <owner> <repo>   (or set OWNER=, REPO= env vars)" >&2
    exit 2
fi

FULL="${OWNER}/${REPO}"

if ! command -v gh >/dev/null 2>&1; then
    echo "error: gh CLI not installed (brew install gh | https://cli.github.com)" >&2
    exit 2
fi
if ! gh auth status >/dev/null 2>&1; then
    echo "error: gh CLI not authenticated; run 'gh auth login' first" >&2
    exit 2
fi

echo "==> Applying GitHub settings to ${FULL}"
echo

echo "=== 1. Code security and analysis ==="
gh api -X PATCH "/repos/${FULL}" \
    -F 'security_and_analysis[secret_scanning][status]=enabled' \
    -F 'security_and_analysis[secret_scanning_push_protection][status]=enabled' \
    -F 'security_and_analysis[dependabot_security_updates][status]=enabled' \
    >/dev/null
echo "    secret_scanning + push_protection + dependabot_security_updates: enabled"

echo
echo "=== 2. Private Vulnerability Reporting ==="
gh api -X PUT "/repos/${FULL}/private-vulnerability-reporting" >/dev/null
echo "    PVR: enabled"

echo
echo "=== 3. Merge settings ==="
gh api -X PATCH "/repos/${FULL}" \
    -F delete_branch_on_merge=true \
    -F allow_squash_merge=true \
    -F allow_merge_commit=false \
    -F allow_rebase_merge=true \
    -F allow_auto_merge=false \
    >/dev/null
echo "    delete_branch_on_merge=true, squash+rebase only, auto-merge off"

echo
echo "=== 4. Branch protection (main) ==="
if [ -x "${REPO_ROOT}/scripts/setup-branch-protection.sh" ]; then
    bash "${REPO_ROOT}/scripts/setup-branch-protection.sh" "${FULL}"
else
    echo "    warning: scripts/setup-branch-protection.sh not found / not executable; skipped"
fi

echo
echo "==> Done. Manual TODOs (= cannot automate, follow these links to apply):"
echo "    - Secret scanning 'Non-provider patterns' (= Secret Protection bundle)"
echo "      https://github.com/${FULL}/settings/security_analysis"
echo "    - Code scanning (CodeQL) default setup (= UI button only)"
echo "      https://github.com/${FULL}/settings/security_analysis"
echo "    - Repo description / topics / homepage (= per-project metadata)"
echo "      https://github.com/${FULL}/settings"
