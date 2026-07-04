# Contributing

Issues welcome — bug reports, feature requests, and technical-debt notes go to the templates under `.github/ISSUE_TEMPLATE/`.

Pull requests should be based on an existing issue; trivial fixes (typos, small doc tweaks) may be sent directly. Merge decisions rest with the repo owner.

By contributing you agree that your contribution is licensed under the terms in `LICENSE`.

## How changes are verified

This repository intentionally runs no CI — every quality gate (lint,
tests, docs freshness, audits) is local-first so the whole suite works
offline and in forks. For external pull requests the maintainer checks
out the branch and runs the full gate suite locally before merging, so
expect review comments quoting concrete gate output instead of a bot
status check. You can run the same gates yourself with `task --list`.
