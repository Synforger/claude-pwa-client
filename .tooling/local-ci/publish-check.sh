#!/usr/bin/env bash
# =============================================================================
# publish-check — pre-publication gate for flipping a repo private -> public
# =============================================================================
# Flipping visibility exposes the ENTIRE history retroactively, so this gate
# checks the past, not just the working tree:
#
#   1. full-history secret scan            (gitleaks detect, all commits)
#   2. full-history / multi-source anon audit (guard-dispatcher, when armed)
#   3. OSS surface: LICENSE present, no {{placeholder}} left in the
#      contributor-facing files, README.md exists
#
# Exit 0 = safe to publish. Any finding = exit 1, do not flip visibility.
# Judgement only — this script never rewrites history; scrub with
# git-filter-repo manually if something is found.
# =============================================================================

set -uo pipefail

FAIL=0
say()  { printf '%s\n' "$*"; }
ok()   { printf 'ok:   %s\n' "$*"; }
bad()  { printf 'FAIL: %s\n' "$*" >&2; FAIL=1; }
skip() { printf 'skip: %s\n' "$*"; }

say "=== publish-check: full-history + OSS surface gate ==="

# ---- 1. secrets across the whole history -----------------------------------
if command -v gitleaks >/dev/null 2>&1; then
    if gitleaks detect --no-banner --redact >/dev/null 2>&1; then
        ok "gitleaks: full history clean"
    else
        bad "gitleaks found secrets in history — scrub before publishing"
    fi
else
    bad "gitleaks not installed (brew install gitleaks) — history unchecked"
fi

# ---- 2. deep anon audit (guard-dispatcher, optional armament) ---------------
DEEP="$HOME/.git-hooks/scanners/anon-audit-deep.sh"
if [ -f "${DEEP}" ]; then
    if bash "${DEEP}" >/dev/null 2>&1; then
        ok "deep anon audit: all sources clean"
    else
        bad "deep anon audit found identifiers — run it directly for details"
    fi
else
    skip "guard-dispatcher not armed on this machine — anon history unchecked"
fi

# ---- 3. OSS surface ----------------------------------------------------------
[ -f LICENSE ] && ok "LICENSE present" || bad "LICENSE missing"
[ -f README.md ] && ok "README.md present" || bad "README.md missing"

leftover="$(grep -rlE '\{\{[a-z_]+\}\}' README.md README.ja.md SECURITY.md CONTRIBUTING.md ROADMAP.md THIRD_PARTY_NOTICES.md 2>/dev/null || true)"
if [ -z "${leftover}" ]; then
    ok "no template placeholders left in contributor-facing files"
else
    bad "unfilled {{placeholders}} in: $(printf '%s' "${leftover}" | tr '\n' ' ')"
fi

echo
if [ "${FAIL}" -eq 0 ]; then
    ok "publish-check: safe to flip this repository public"
    exit 0
fi
bad "publish-check: do NOT publish until the findings above are resolved"
exit 1
