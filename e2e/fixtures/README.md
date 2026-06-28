# fixtures/

Two flavours:

- **`sessions/<sid>.jsonl`** — a full claude session in JSONL form. One event per line, server-stamped uuid. `global-setup.js` mirrors these into `_runtime/jsonl/` so the watcher tails them like a real session. Use this for scenarios that need a pre-populated history (= chat replay, fork from message, refresh syncs).
- **`replay/<name>.json`** — a timed sequence pushed through `POST /debug/replay`. Use this when the bug is about *server* ordering / dedup / heartbeat / late arrival rather than initial-load shape.

`_runtime/` is gitignored and recreated per playwright run by `helpers/run-backend.mjs` and `helpers/global-setup.js`. Never commit anything there.

## Conventions

- sid prefix `e2e-` so they never collide with real history if a fixture leaks.
- uuid stable across re-runs (= write them once, do not regenerate).
- bytes are valid UTF-8 unless the scenario is specifically about boundary decoding.
- timestamps are integer ms since epoch, ordered ascending within a file.
