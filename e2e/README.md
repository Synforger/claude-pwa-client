# e2e — playwright scenarios for claude-pwa-client v2

W4 deliverable. Pins the contract between the v2 backend (= contracts/ + observability/) and the v2 frontend (= features/ + transport/) by exercising real browser sessions against a test-mode backend.

## Layout

```
e2e/
├── README.md                ← this file
├── package.json             ← playwright + @playwright/test devDep only
├── playwright.config.js     ← projects (chromium-desktop + webkit-mobile), webServer hook
├── .gitignore               ← node_modules / test-results / playwright-report / fixtures/_runtime
├── helpers/
│   ├── run-backend.mjs      ← test-mode backend launcher (uvicorn + stub config + tmp data dir)
│   ├── global-setup.js      ← seed fixtures into the runtime data dir
│   ├── global-teardown.js   ← purge tmp dir after the run
│   ├── replay.js            ← /debug/replay client (pushes fixture events into a live SSE stream)
│   └── pwa.js               ← `openClient(page)` boilerplate (mount frontend, wait for first SSE)
├── fixtures/
│   ├── README.md            ← fixture conventions + how to add a new one
│   ├── _runtime/            ← gitignored, created by global-setup, removed by teardown
│   ├── sessions/<sid>.jsonl ← per-sid JSONL fixtures (claude format, uuid-stamped)
│   └── replay/<name>.json   ← timed event sequences for /debug/replay
└── scenarios/
    ├── _regression/         ← direct regression of recent production bugs
    │   ├── reconcile-no-duplicate.spec.js
    │   ├── bg-fg-resume.spec.js
    │   ├── tab-switch-isolation.spec.js
    │   ├── send-then-input-restored.spec.js
    │   └── terminal-utf8-boundary.spec.js
    ├── _golden/             ← 14 feature golden paths (1:1 with feature-inventory.md categories)
    └── _contract/           ← contract-level guards (heartbeat / DNS rebinding / refresh sync)
```

## Run

```bash
cd ~/repos/claude-pwa-client.v2/e2e
npm ci
npx playwright install --with-deps chromium webkit
npm test
```

For an iterated debug loop attach to a pre-launched backend:

```bash
CPC_E2E_KEEP_BACKEND=1 \
CPC_E2E_BASE_URL=http://127.0.0.1:18765 \
  node ./helpers/run-backend.mjs &
CPC_E2E_KEEP_BACKEND=1 npm test
```

The backend launcher binds to **18765** by default (= avoids the dev / prod 8765 LaunchAgent listener). It runs with `CPC_CLAUDE_PATH=/usr/bin/true` and a freshly created `fixtures/_runtime/data/` so it never touches the operator's real chat history.

## "bug → fixture → scenario" loop (= core principle)

Every regression we ship must arrive here as a deterministic fixture, not a flake. The shape:

1. Reproduce the bug in a v2 fixture (`fixtures/sessions/<sid>.jsonl` or `fixtures/replay/<name>.json`).
2. Add a scenario in `scenarios/_regression/` that asserts the **expected** post-fix behaviour. Run it red against the buggy build first.
3. Land the fix on `v2-architecture`. Re-run; the scenario goes green and stays green from then on.

The scenario file name encodes the bug — it should still grep for the issue years later.

## Coverage check (= inventory ↔ scenarios)

`scripts/check-coverage.mjs` (in this directory) walks the feature inventory and the `scenarios/_golden/` directory; any feature category without a matching spec fails the run. CI wires this to the post-test step. The inventory path is configurable via `CPC_E2E_INVENTORY` so the script stays runnable from any checkout.
