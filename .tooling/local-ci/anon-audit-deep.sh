#!/usr/bin/env bash
# =============================================================================
# 全 source 横断の deep anon audit (= scanner 強化版)
# =============================================================================
# 通常の anon-scan.sh (= tracked file 内 literal scan) に加えて、 公開可能性
# に関わる全 source を一気に走査する deep audit。
#
# 検査範囲 (= 10 source):
#   1. 全 tracked file (= anon-scan.sh 経由)
#   2. 全 git history blob (= git log --all -p)
#   3. 全 commit message + body
#   4. 全 branch 名 (= local + remote)
#   5. 全 tag 名 + tag annotation 本文
#   6. 全 commit author + committer email + name
#   7. GitHub PR title / body / labels (= gh api)
#   8. GitHub Issue title / body
#   9. GitHub repo description / topics / homepage
#  10. GitHub releases (= title + body + tag)
#
# gh CLI 未 install / 未認証なら 7-10 を skip 警告。 git 履歴系 1-6 は git
# だけで実行可能。
#
# 使い方:
#   bash _core/.tooling/local-ci/anon-audit-deep.sh
#   task audit:deep    (= Taskfile 経由)
#
# Exit:
#   0 = 全 source clean
#   1 = どこかに leak (= source 別件数 + 内訳を表示)
#   2 = 設定エラー (= anon-words.txt 不在 等)
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

WORDS_FILE="${SCRIPT_DIR}/anon-words.txt"
if [ ! -f "${WORDS_FILE}" ]; then
    log_fail "anon-words.txt が見つからない (${WORDS_FILE}): operator masterから sync してください (bash ${SCRIPT_DIR}/anon-sync-truth.sh)"
    exit 2
fi

# 真値を 1 行 1 pattern として読み、 | で連結して PCRE 化
ANON_PATTERN="$(grep -v '^#' "${WORDS_FILE}" | grep -v '^$' | sed -E 's/[[:space:]]+#.*$//' | tr '\n' '|' | sed 's/|$//')"
if [ -z "${ANON_PATTERN}" ]; then
    log_fail "anon-words.txt に有効な pattern なし"
    exit 2
fi
export ANON_PATTERN

# 共通 perl scanner (= 全 source で再利用)
scan_perl() {
    perl -ne 'BEGIN { $re = qr{(?i)$ENV{ANON_PATTERN}} } if (/$re/) { print "$&\n" }' 2>/dev/null | sort -u
}

count_hits() {
    local label="$1" hits="$2"
    local n
    n=$(printf "%s" "${hits}" | grep -c . 2>/dev/null || true)
    if [ "${n}" -eq 0 ]; then
        log_ok "${label}: clean"
    else
        log_fail "${label}: ${n} 件 = $(printf "%s" "${hits}" | tr '\n' ' ')"
    fi
    echo "${n}"
}

total=0

# --- source 1: tracked file (= anon-scan.sh 経由) ---
printf '\n=== source 1/10: tracked files (= anon-scan.sh) ===\n' >&2
if bash "${SCRIPT_DIR}/anon-scan.sh" >/dev/null 2>&1; then
    log_ok "tracked files: clean"
else
    log_fail "tracked files: leak あり (= bash anon-scan.sh で詳細確認)"
    total=$((total + 1))
fi

# --- source 2: 全 git history blob ---
printf '\n=== source 2/10: git history blob (= 全 commit の全 diff) ===\n' >&2
hits=$(git log --all -p 2>/dev/null | scan_perl)
n=$(count_hits "git history blob" "${hits}")
total=$((total + n))

# --- source 3: 全 commit message ---
printf '\n=== source 3/10: commit messages ===\n' >&2
hits=$(git log --all --pretty='format:%H %s%n%b' 2>/dev/null | scan_perl)
n=$(count_hits "commit messages" "${hits}")
total=$((total + n))

# --- source 4: branch 名 ---
printf '\n=== source 4/10: branch names ===\n' >&2
hits=$(git branch -a 2>/dev/null | scan_perl)
n=$(count_hits "branch names" "${hits}")
total=$((total + n))

# --- source 5: tag 名 + annotation ---
printf '\n=== source 5/10: tag names + annotations ===\n' >&2
tag_text=$(git tag -l 2>/dev/null; for t in $(git tag -l 2>/dev/null); do git tag -l --format='%(contents)' "$t" 2>/dev/null; done)
hits=$(printf "%s" "${tag_text}" | scan_perl)
n=$(count_hits "tags" "${hits}")
total=$((total + n))

# --- source 6: author + committer ---
printf '\n=== source 6/10: author + committer email / name ===\n' >&2
hits=$(git log --all --pretty='format:%an <%ae> / %cn <%ce>' 2>/dev/null | scan_perl)
n=$(count_hits "author/committer" "${hits}")
total=$((total + n))

# --- source 7-10: GitHub metadata (= gh CLI 経由) ---
if ! command -v gh >/dev/null 2>&1; then
    log_warn "gh CLI 未 install、 GitHub 側 source 7-10 を skip"
elif ! gh auth status >/dev/null 2>&1; then
    log_warn "gh CLI 未認証、 GitHub 側 source 7-10 を skip"
else
    # repo 名を git remote から推定。 github.com / github-* SSH alias 両対応。
    # BSD sed の ERE が alternation + quantifier で詰むので python に逃す。
    remote_url=$(git remote get-url origin 2>/dev/null || echo "")
    repo=$(printf '%s' "${remote_url}" | python3 -c "
import re, sys
m = re.match(r'^(?:git@[^:]+:|https?://[^/]+/)([^/]+)/([^/.]+)(?:\.git)?$', sys.stdin.read().strip())
print(f'{m.group(1)}/{m.group(2)}' if m else '')
")

    if [ -z "${repo}" ]; then
        log_warn "remote origin が GitHub URL でない、 GitHub 側 source 7-10 を skip"
    else
        # --- source 7: PR title/body ---
        printf '\n=== source 7/10: GitHub PR title/body ===\n' >&2
        hits=$(gh pr list --repo "${repo}" --state all --limit 200 --json title,body 2>/dev/null | scan_perl)
        n=$(count_hits "GitHub PRs" "${hits}")
        total=$((total + n))

        # --- source 8: Issue title/body ---
        printf '\n=== source 8/10: GitHub Issues title/body ===\n' >&2
        hits=$(gh issue list --repo "${repo}" --state all --limit 200 --json title,body 2>/dev/null | scan_perl)
        n=$(count_hits "GitHub Issues" "${hits}")
        total=$((total + n))

        # --- source 9: repo description + topics + homepage ---
        printf '\n=== source 9/10: GitHub repo description / topics / homepage ===\n' >&2
        hits=$(gh repo view "${repo}" --json description,topics,homepageUrl 2>/dev/null | scan_perl)
        n=$(count_hits "GitHub repo metadata" "${hits}")
        total=$((total + n))

        # --- source 10: releases ---
        printf '\n=== source 10/10: GitHub releases ===\n' >&2
        hits=$(gh release list --repo "${repo}" --limit 100 --json name,body,tagName 2>/dev/null | scan_perl)
        n=$(count_hits "GitHub releases" "${hits}")
        total=$((total + n))
    fi
fi

printf '\n' >&2
if [ "${total}" -eq 0 ]; then
    log_ok "deep audit: 全 source clean (= 0 件)"
    exit 0
fi
log_fail "deep audit: 合計 ${total} 件 leak"
exit 1
