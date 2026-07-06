# Contributing

Issues welcome — bug reports, feature requests, and technical-debt notes go to the templates under `.github/ISSUE_TEMPLATE/`.

Pull requests should be based on an existing issue; trivial fixes (typos, small doc tweaks) may be sent directly. Merge decisions rest with the repo owner.

By contributing you agree that your contribution is licensed under the terms in `LICENSE`.

## How changes are verified

Every quality gate (lint, tests, docs freshness, audits) is local-first —
the whole suite works offline and in forks, and you can run it yourself
with `task --list` (`task ci` is the full set). A thin GitHub Actions
mirror (`.github/workflows/ci.yml`) runs the same `task ci` on pull
requests, so external PRs get a status check without owning the guard
machinery; the checks themselves live in the repository, never only in
CI. The maintainer additionally runs the full gate suite locally before
merging.
