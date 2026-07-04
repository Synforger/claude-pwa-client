# GitHub Actions policy for this template

Two-tier policy, one implementation:

- **The local gate suite is the source of truth.** Every check (lint,
  tests, docs freshness, version drift, audits) lives in the Taskfile +
  `.tooling/` and runs offline. Nothing is implemented inside a
  workflow file.
- **`ci.yml` is a thin trigger, not a second implementation.** On pull
  requests it runs the exact same `task ci` the maintainer runs
  locally, so external contributors get a status check without owning
  any of the guard machinery.
- **Visibility guard:** every workflow starts with
  `if: ${{ !github.event.repository.private }}`. Runner minutes are
  free on public repositories; on a private repository the workflow
  refuses to run, so it can never consume the plan's minute quota.
  While a repo is private (including a repo that will go public
  later), the trigger is the maintainer's discipline instead: run
  `task ci` before every merge.

## What is enabled

- `ci.yml` — `task ci` (lint + unit tests + docs:check + lint:versions)
  on pull requests, public repos only.
- `version-bump.yml` — shipped disabled (`if: false`); version bumps
  happen locally via `task version:bump`.

## Local-only by design

| Concern             | Where it runs                                                        |
|---------------------|----------------------------------------------------------------------|
| Anonymity / identity | guard-dispatcher hooks (pre-commit / commit-msg / pre-push) + `task audit:deep` |
| Dependency audit    | `task audit` (aggregate, on demand / scheduled)                      |
| Version bump        | `task version:bump`                                                  |
| Release packaging   | `task release:cut`                                                   |
| Pre-publication gate | `task publish:check` (full-history audits before flipping private -> public) |

## Why the anonymity scan can never move to CI

CI runs **after** push — for an identity leak that is already too
late, because the diff is public the moment it lands. Additionally the
word list is private operator data and is never committed, so CI has
nothing meaningful to scan against. The pre-push dispatcher deep-scans
the outgoing range before anything crosses the boundary.

## Adding more workflows

Keep the invariant: a workflow may only *invoke* `task` verbs that
also run locally. The moment a check exists only in CI, the local
suite stops being the source of truth and the repo stops working
offline.
