---
name: client-operations
description: Work on, check, deploy and restart the claude-pwa-client install: where its repo, configuration and state are, the checks that guard commits, how to ship a change to the running backend, and how to back up and restart a resident service without losing its state.
when_to_use: Before touching the client's repo, its running backend or its configuration (even a single curl) / before restarting, killing or moving the persistent files of a resident service / when the operator voices worry that something will break or be lost.
---

# Running claude-pwa-client

The client is a PWA plus a backend that the operator uses every day. A mistake stops their work at once, so treat the
running backend as production.

## Where things are

In an agent platform, the client's checkout is `$AGENT_PLATFORM_ROOT/tools/claude-pwa-client`. Its configuration
is `$AGENT_PLATFORM_ROOT/config/claude-pwa-client/config.json`; its records and state are under
`$AGENT_PLATFORM_ROOT/state/claude-pwa-client/` (`data/`, `logs/`, `backups/`, `page-store/`, `uploads/`) and its
keys under `$AGENT_PLATFORM_ROOT/secrets/claude-pwa-client/`. The authority for all of these paths is
`backend/_common/paths.py`. A tab's memo is not among them: it lives in the agent's own folder
(`<tier folder>/pages/<tab id>/memo.md`). Without a platform root the older locations apply (see
`docs/reference/config.md`).

Each machine has its own port, resident-service name and configuration. Read them from the client's configuration
for this machine and from `.env` in the checkout (`PORT`, `LAUNCH_AGENT_LABEL`); never assume them, and say the
port when you speak about "production" on a machine that has several.

Read `README.md` first, then only what the task needs: for the backend, `backend/main.py` and then the router in
question; for the screen, `frontend/src/App.jsx` and the hook or component. Documents for users are in
`docs/setup/`, `docs/reference/` and `docs/troubleshooting/`; for contributors in `docs/internals/`.

## Checks

The checks live in the checkout (`Taskfile.yml` and `.tooling/`), and CI only calls `task ci`. The commit-time gates
are in `.githooks/pre-commit`: flake8 for staged backend Python, ESLint for staged frontend files, gitleaks, and the
audit for state duplication in the frontend. `task ci` runs lint, tests, docs freshness, version drift and contract
drift. The end-to-end scenarios (`tests/e2e/`) are not part of `task ci`; run them when a change touches the screen or the
send/receive path.

- **Do not enable the hooks in the repo.** Git reads one `core.hooksPath`; setting it locally switches off the
  machine-wide guard that already runs `.githooks/`.
- A new gate goes into `.tooling/local-ci/` and a staged-condition block in `.githooks/pre-commit`. Gates about
  identity belong to the machine-wide guard.
- A false positive of the frontend audit is added to `.tooling/local-ci/audit-w2-residue-allowlist.txt`.
- Run the end-to-end scenarios isolated: `run-backend.mjs` forces its own tmux socket (`CPC_TMUX_SOCKET`, `cpc-e2e`
  by default). Never bypass it: tmux's namespace is global to the user, and a test backend would take the
  operator's real sessions for leftovers and kill them.

## Working with the running backend

- **Do not probe it unless asked.** A curl, a websocket or SSE connection test, opening the PWA in a browser, or any
  call that changes backend state can disconnect the tab the operator is using, and away from home they cannot
  recover. The exceptions are the commands an agent uses to do its work: `tabs` (messages, children, rollover).
- `task build` is safe to run on your own judgement.
- To try Claude's behaviour for real (how Esc is handled, say), do it in a tab that shows in the PWA's list, not in a
  hidden tmux session, so the operator can see what runs. Add a laboratory agent to the configuration only after
  asking, since it appears in the new-conversation list.

## Shipping a change to the running backend

Each machine's backend runs the code and the built screen of its own checkout. A change that landed on `develop`
reaches the running backend only after that checkout has pulled and built.

On an agent platform whose manifest marks the client `auto_update`, the `platform update` service does this on every
machine every 10 minutes: it moves the checkout to the head of `develop` (only when it is on `develop`, has no local
change and has not diverged), runs `task build`, syncs the environment when `pyproject.toml` or `uv.lock` changed,
and restarts the backend when `backend/`, `pyproject.toml` or `uv.lock` changed. While a voice call's worker runs it
holds the restart, and a later run does it. What it did is in `$AGENT_PLATFORM_ROOT/state/platform/logs/update.out`
(a run with nothing to do writes no line); what is still owed is in `state/platform/update.json`. A merged change
therefore needs no hand to reach the machines. Ship by hand with the steps below when it must be live at once, such
as before a check on a device; the next run then finds nothing to do.

1. Note the current commit: `git rev-parse HEAD`.
2. `git pull --ff-only origin develop` (it works only on `develop` with no local change; read the reason when it stops).
3. `task build`. A screen that is open switches to the new build the next time it is in front.
4. See whether backend files changed: `git diff --stat <noted commit>..HEAD -- backend/ pyproject.toml uv.lock`.
   No change: done.
   - The resident service runs its environment's own `uvicorn` directly and does not sync dependencies when it
     starts. If `pyproject.toml` or `uv.lock` changed, bring the environment in line before restarting: on an agent
     platform, `$AGENT_PLATFORM_ROOT/manifest/bin/platform build` (it also writes the service's plist, so do not edit
     the plist by hand); elsewhere, install them into the environment the service runs.
   - Then, from the repo folder, check `<environment>/bin/python -c "import backend.main"`.
5. If backend files changed, restart through the resident service (below) and report it in one line. After the plist
   was rewritten, restart with `launchctl bootout` then `launchctl bootstrap`: `kickstart -k` starts from the plist it
   read before. Bootstrap only once the old one has left launchd (see Restart path below).
   - The resident process must not carry `UV_PROJECT_ENVIRONMENT`. Tabs the backend starts inherit its environment,
     and a `uv run` in any of them rebuilds the backend's environment with another project's dependencies (the
     backend then fails to send files, images and pages). After a restart, `ps -E -p <pid>` must not show it.

## Resident services: back up, restart, observe

Persistent files cannot be recovered once lost. Protect them at two points: before the change, and after the start.

### Before: back up

Before a kill, restart, move or path switch, copy the service's whole persistent area to a path **outside** the
service's folder (a copy inside gets read by the service as a snapshot).

- Take `state/<tool>/`, `config/<tool>/` and `secrets/<tool>/` of the platform root entirely, and any `config*.json`,
  `sessions*.json`, `*.db`, `*.sqlite` inside the repo (ignored by git or not). The client's
  `$AGENT_PLATFORM_ROOT/state/claude-pwa-client/backups/` is where updates put their copies.
- **List the folder with `find -type f` before deciding what to copy.** A backup of the two or three files you know
  misses the ones you did not know existed (a key, the tab list).
- Look at the copy with `ls -la`: no zero-byte files, no empty folders.
- Without a backup, kill/restart/delete only after the operator said a backup is not needed.
- If the operator says it might break or lose data ("is this safe?"), take the backup **first** and explain after.
  Do not answer a worry with an argument that it cannot happen.

### Restart path

Start a service only through the resident mechanism (the LaunchAgent on macOS). A hand-started `nohup … &` is an
emergency measure with the operator's approval, and must be folded back into the resident mechanism in the same
session. If bootstrap or load fails, dig until the cause is known. `launchctl list` shows the name
this machine uses; `task restart` kickstarts it but ends with a probe, so use the LaunchAgent directly when a probe
is unwanted.

When writing a plist: never rebuild it from a minimal template. Diff it fully against the existing one and change only
the difference. Check `Label` (differs from existing ones), `ProgramArguments` (absolute paths, the interpreter of the
environment called directly), `WorkingDirectory` (absolute), `EnvironmentVariables` (`PATH` must include
`/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin`; launchd's own `PATH` hides Homebrew tools, so every
tool called by a relative path fails), `RunAtLoad` and `KeepAlive` both true for a resident service,
`StandardOutPath` and `StandardErrorPath` (absolute; if they equal a log file the service holds open, bootstrap fails
with an I/O error, so kill the old process first). Validate with `plutil -lint`. Examples are in `docs/setup/launchd/`.

The same `Bootstrap failed: 5: Input/output error` comes when the label is still loaded: `launchctl bootout` returns
before a service with open terminals has left launchd. Before bootstrapping the same label again, wait until
`launchctl print gui/<uid>/<label>` fails (exit 113).

### After: observe

An answering endpoint is not enough: within 1 to 30 seconds PTY spawn failures, `OSError: Too many open files`,
`FileNotFoundError` and key load failures can follow.

- Watch the error log for 30 seconds after the start (`task logs`) and fix every ERROR, Exception, OSError and
  FileNotFoundError.
- "Done" means a real path was exercised once (a PTY spawn, a websocket, a push), not a single `/healthz`.

### Rebuilding the tab list

If the persistent copy is gone and the tab list must be rebuilt from metadata, do **not** load everything: the file
descriptors, PTY devices and watchers hit the system limit. Restore only the tabs in use, say the size up front
("restoring 9 would reach the descriptor limit; starting with 4, the rest as you decide"), and add more on the
operator's word.

## The iPhone app

The iPhone app (`shell/`) and its build are described in `docs/setup/ios-app.md`; an agent can drive the app's
device functions through `cpc device <kind> <operation>` (`docs/reference/device-ops.md`). `task ios:crashes
DEVICE=<id>` collects crash records from a connected iPhone, `task lint` includes `ios-privacy-check` for missing
usage descriptions. Operations that delete or change things are done only when the operator says so.
