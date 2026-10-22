#!/usr/bin/env node
// playwright webServer launcher.
// Boots the v2 backend on port 18765 (≠ prod 8765 LaunchAgent) with a tmp
// data dir + minimal config + stub claude binary so the operator's real chat
// history is never touched. SIGINT / SIGTERM tear the child down cleanly.
import { spawn, spawnSync } from 'node:child_process'
import { mkdirSync, writeFileSync, rmSync, existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const E2E_ROOT = resolve(__dirname, '..')
const REPO_ROOT = resolve(E2E_ROOT, '..', '..')

const RUNTIME = resolve(E2E_ROOT, 'fixtures', '_runtime')
const DATA_DIR = resolve(RUNTIME, 'data')
const LOGS_DIR = resolve(RUNTIME, 'logs')
const SECRETS_DIR = resolve(RUNTIME, 'secrets')
// What the user and their agents write (favorites.txt). The default is under the real HOME,
// so the test backend gets its own, or a run would rewrite the operator's list.
const USER_DIR = resolve(RUNTIME, 'user')
// The folder the test agents run in. A tab's memo is written under it (`pages/<tab id>/memo.md`), so it is not
// the real HOME.
const AGENT_DIR = resolve(RUNTIME, 'agent')
const CONFIG_PATH = resolve(RUNTIME, 'config.json')

const PORT = process.env.CPC_E2E_PORT || '18765'

// Fresh tmp tree per launch — global-teardown also wipes this but a crashed
// run could leave stale files. Idempotent.
rmSync(RUNTIME, { recursive: true, force: true })
mkdirSync(DATA_DIR, { recursive: true })
mkdirSync(LOGS_DIR, { recursive: true })
mkdirSync(SECRETS_DIR, { recursive: true, mode: 0o700 })
mkdirSync(USER_DIR, { recursive: true })
mkdirSync(AGENT_DIR, { recursive: true })

// Isolate the e2e account's claude config dir to fixtures/_runtime/.claude
// so the resolved projects dir is fixtures/_runtime/.claude/projects, NOT
// the operator's real ~/.claude/projects. Without this override
// backend._common.config._projects_dirs_from_accounts falls back to $HOME/.claude
// and the seed channel happily writes JSONL into the real chat tree.
const E2E_CLAUDE_DIR = resolve(RUNTIME, '.claude')
mkdirSync(E2E_CLAUDE_DIR, { recursive: true })
// A second account whose Claude Code settings ask for Japanese, for the scenarios about prose
// written in another language (= the first account stays without a language, so English fixtures render as is).
const E2E_JA_CLAUDE_DIR = resolve(RUNTIME, '.claude-ja')
mkdirSync(E2E_JA_CLAUDE_DIR, { recursive: true })
writeFileSync(resolve(E2E_JA_CLAUDE_DIR, 'settings.json'), JSON.stringify({ language: '日本語' }))

const config = {
  agents: {
    agent_e2e: {
      cwd: AGENT_DIR,
      model: 'Opus',
      display_name: 'E2E Agent',
      launch_alias: 'agent_e2e',
    },
    // An agent with a voice that also listens. The speech and listening engines are the
    // test backend's own fixtures (= backend/routes/debug_e2e.py), standing in for engine processes.
    agent_e2e_voice: {
      cwd: AGENT_DIR,
      model: 'Opus',
      display_name: 'E2E Voice Agent',
      launch_alias: 'agent_e2e_voice',
      voice: {
        engine: `http://127.0.0.1:${PORT}/ext/fixture-voice`,
        speaker: 1,
        marks: { calm: { speedScale: 1.1 }, happy: { speedScale: 1.2 } },
        default: 'calm',
        // CPC_E2E_LISTEN_ENGINE / CPC_E2E_TURN_MODEL point the agent at a real listening engine and a
        // real Smart Turn model (= the live scenario, scenarios/live/voice-conversation.spec.js).
        listen: {
          engine: process.env.CPC_E2E_LISTEN_ENGINE || `http://127.0.0.1:${PORT}/ext/fixture-listen`,
          ...(process.env.CPC_E2E_TURN_MODEL ? { turn: process.env.CPC_E2E_TURN_MODEL } : {}),
        },
      },
    },
  },
  accounts: {
    e2e: {
      display_name: 'E2E',
      env: { CLAUDE_CONFIG_DIR: E2E_CLAUDE_DIR },
    },
    e2e_ja: {
      display_name: 'E2E (Japanese)',
      env: { CLAUDE_CONFIG_DIR: E2E_JA_CLAUDE_DIR },
    },
  },
  // Served by the test backend itself (= backend/routes/debug_e2e.py fixture_router),
  // standing in for an extension that Tailscale Serve would mount in production.
  // The second one opens as a page (the whole space above the chat input) instead of a band.
  extensions: [
    { id: 'fixture', title: 'Fixture', icon: '🧪' },
    { id: 'fixture-page', title: 'Fixture page', icon: '📄', view: 'page' },
  ],
  claude_path: '/usr/bin/true',
  cors_allow_origins: ['*'],
}
writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2))

// VAPID is generated lazily by backend/cli/gen_vapid.py in prod; for e2e a
// throwaway pair is fine. Push scenarios run against a mock subscription anyway.
const vapidPath = resolve(SECRETS_DIR, 'vapid.json')
if (!existsSync(vapidPath)) {
  writeFileSync(vapidPath, JSON.stringify({
    public_key: 'BDe2eMockPublicKeyDoNotUseInProductionDoNotUseInProductionAA',
    private_key: 'e2eMockPrivateKeyDoNotUseInProductionAA',
    subject: 'mailto:e2e@example.invalid',
  }, null, 2))
}

// tmux socket isolation (2026-07-15, resume-storm incident): tmux's namespace
// is user-global, so port/data-dir isolation alone is NOT enough — this
// backend's maintenance would see the operator's production pwa-* sessions
// as unmanaged leftovers and kill them (which then fight the prod backend's
// auto-resume in a loop). Every tmux call in the backend goes through
// tmux_base_argv(), which honours CPC_TMUX_SOCKET, so the e2e backend lives
// on its own socket and can never touch the default-socket sessions.
const TMUX_SOCKET = process.env.CPC_TMUX_SOCKET || 'cpc-e2e'

const env = {
  ...process.env,
  CPC_DATA_DIR: DATA_DIR,
  CPC_LOGS_DIR: LOGS_DIR,
  CPC_SECRETS_DIR: SECRETS_DIR,
  CPC_USER_DIR: USER_DIR,
  CPC_CONFIG_PATH: CONFIG_PATH,
  CPC_E2E: '1',
  CPC_TMUX_SOCKET: TMUX_SOCKET,
  PYTHONUNBUFFERED: '1',
}

// Single-stage spawn: resolve the python binary up front so SIGTERM reaches
// uvicorn directly. A launcher such as `uv run` adds a process layer that swallows
// signals (= orphans uvicorn on teardown), so we bypass it.
//
// Resolution order:
//   1. $CPC_E2E_PYTHON                       (= explicit override)
//   2. <repo>/.venv/bin/python3              (= what `uv sync` / `task setup` builds)
//   3. `python3` on PATH                     (= last resort)
const candidates = [
  process.env.CPC_E2E_PYTHON,
  resolve(REPO_ROOT, '.venv', 'bin', 'python3'),
].filter(Boolean)
const pythonBin = candidates.find((p) => existsSync(p)) || 'python3'

const child = spawn(pythonBin, [
  '-m', 'uvicorn', 'backend.main:app',
  '--host', '127.0.0.1', '--port', PORT,
], {
  cwd: REPO_ROOT,
  env,
  stdio: ['ignore', 'inherit', 'inherit'],
})

// Tear down the isolated tmux server (kills any fixture sessions + their
// stub processes). Safe by construction: it only ever addresses the e2e
// socket, never the default one.
// Synchronous, so it has finished before this process exits (an asynchronous spawn from an exit handler may never run).
const killE2eTmuxServer = () => {
  try {
    spawnSync('tmux', ['-L', TMUX_SOCKET, 'kill-server'], { stdio: 'ignore', timeout: 5_000 })
  } catch (_) { /* tmux absent / server already gone */ }
}

let shuttingDown = false
const shutdown = (sig) => {
  if (shuttingDown) return
  shuttingDown = true
  try { child.kill(sig) } catch (_) { /* benign: child already gone */ }
  killE2eTmuxServer()
  // hard fallback if uvicorn ignores SIGTERM (= during long shutdown hooks)
  setTimeout(() => { try { child.kill('SIGKILL') } catch (_) {} }, 5_000).unref()
}
process.on('SIGINT', () => shutdown('SIGINT'))
process.on('SIGTERM', () => shutdown('SIGTERM'))
process.on('exit', () => {
  try { child.kill('SIGTERM') } catch (_) { /* benign */ }
  killE2eTmuxServer()
})

child.on('exit', (code, sig) => {
  process.exitCode = code ?? (sig ? 1 : 0)
})
