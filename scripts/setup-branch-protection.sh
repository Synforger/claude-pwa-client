#!/bin/bash
set -e

# Setup branch protection using GitHub Rulesets
# Usage: ./scripts/setup-branch-protection.sh
#
# Single-maintainer public-OSS profile:
#   - main + develop (feature -> develop -> main, three-tier flow)
#   - PR required, 0 approvals (= self-merge allowed, but always via PR)
#   - no required status checks (= quality gates are local: task lint /
#     task test:unit / dispatcher hooks; CI is intentionally not a gate)
#   - deletion + force-push blocked; admin bypass kept for emergencies

OWNER="${GITHUB_OWNER:-$(gh repo view --json owner -q .owner.login)}"
REPO="${GITHUB_REPO:-$(gh repo view --json name -q .name)}"

# Repository Role ID for Admin (RepositoryRole type)
REPOSITORY_ADMIN_ROLE_ID=5

echo "Setting up branch protection for repository: ${OWNER}/${REPO}"
echo ""

# Function to create or update a ruleset
create_or_update_ruleset() {
  local ruleset_name="$1"
  local branch_pattern="$2"
  local required_approvals="$3"

  echo "Configuring ruleset: ${ruleset_name}"
  echo "  Branch: ${branch_pattern}"
  echo "  Required approvals: ${required_approvals}"

  # Check if ruleset already exists
  existing_ruleset_id=$(gh api "repos/${OWNER}/${REPO}/rulesets" --jq ".[] | select(.name == \"${ruleset_name}\") | .id" 2>/dev/null || echo "")

  if [ -n "$existing_ruleset_id" ]; then
    echo "  Ruleset already exists (ID: ${existing_ruleset_id}). Updating..."
    METHOD="PUT"
    ENDPOINT="repos/${OWNER}/${REPO}/rulesets/${existing_ruleset_id}"
  else
    echo "  Creating new ruleset..."
    METHOD="POST"
    ENDPOINT="repos/${OWNER}/${REPO}/rulesets"
  fi

  # Create or update ruleset
  result=$(gh api "${ENDPOINT}" --method "${METHOD}" --input - <<EOF
{
  "name": "${ruleset_name}",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["${branch_pattern}"],
      "exclude": []
    }
  },
  "rules": [
    {
      "type": "deletion"
    },
    {
      "type": "non_fast_forward"
    },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": ${required_approvals},
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false
      }
    }
  ],
  "bypass_actors": [
    {
      "actor_id": ${REPOSITORY_ADMIN_ROLE_ID},
      "actor_type": "RepositoryRole",
      "bypass_mode": "always"
    }
  ]
}
EOF
2>&1)

  if echo "$result" | grep -q '"id"'; then
    ruleset_id=$(echo "$result" | jq -r '.id')
    echo "  ✓ Successfully configured (ID: ${ruleset_id})"
  else
    echo "  ✗ Error: Failed to configure ruleset"
    echo "  Error details: $result"
    exit 1
  fi
  echo ""
}

# Remove a ruleset if it exists (used for retired rulesets, e.g. develop).
remove_ruleset_if_present() {
  local ruleset_name="$1"
  local ruleset_id
  ruleset_id=$(gh api "repos/${OWNER}/${REPO}/rulesets" --jq ".[] | select(.name == \"${ruleset_name}\") | .id" 2>/dev/null || echo "")
  if [ -n "${ruleset_id}" ]; then
    echo "Removing retired ruleset: ${ruleset_name} (ID: ${ruleset_id})"
    gh api "repos/${OWNER}/${REPO}/rulesets/${ruleset_id}" --method DELETE >/dev/null
    echo "  ✓ Removed"
    echo ""
  fi
}

# main: PR required, self-merge allowed (0 approvals), no CI gate.
# Receives only develop -> main promotion PRs (releases).
create_or_update_ruleset "Protect main" "refs/heads/main" 0

# develop: PR required, self-merge allowed (0 approvals). Default branch;
# feature branches merge here.
create_or_update_ruleset "Protect develop" "refs/heads/develop" 0

echo "Branch protection setup completed!"
echo "Please verify the rules in GitHub UI: https://github.com/${OWNER}/${REPO}/rules"
