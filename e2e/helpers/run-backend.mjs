#!/usr/bin/env node
// playwright webServer launcher.
// Boots the v2 backend on port 18765 (≠ prod 8765 LaunchAgent) with a tmp
// data dir + minimal config + stub claude binary so the operator's real chat
// history is never touched. SIGINT / SIGTERM tear the child down cleanly.
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync, rmSync, existsSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const E2E_ROOT = resolve(__dirname, '..')
const REPO_ROOT = resolve(E2E_ROOT, '..')

const RUNTIME = resolve(E2E_ROOT, 'fixtures', '_runtime')
const DATA_DIR = resolve(RUNTIME, 'data')
const LOGS_DIR = resolve(RUNTIME, 'logs')
const SECRETS_DIR = resolve(RUNTIME, 'secrets')
const CONFIG_PATH = resolve(RUNTIME, 'config.json')

const PORT = process.env.CPC_E2E_PORT || '18765'

// Fresh tmp tree per launch — global-teardown also wipes this but a crashed
// run could leave stale files. Idempotent.
rmSync(RUNTIME, { recursive: true, force: true })
mkdirSync(DATA_DIR, { recursive: true })
mkdirSync(LOGS_DIR, { recursive: true })
mkdirSync(SECRETS_DIR, { recursive: true, mode: 0o700 })

// Isolate the e2e account's claude config dir to fixtures/_runtime/.claude
// so the resolved projects dir is fixtures/_runtime/.claude/projects, NOT
// the operator's real ~/.claude/projects. Without this override
// backend.config._projects_dirs_from_accounts falls back to $HOME/.claude
// and the seed channel happily writes JSONL into the real chat tree.
const E2E_CLAUDE_DIR = resolve(RUNTIME, '.claude')
mkdirSync(E2E_CLAUDE_DIR, { recursive: true })

const config = {
  agents: {
    agent_e2e: {
      cwd: process.env.HOME || '/tmp',
      model: 'Opus',
      display_name: 'E2E Agent',
      launch_alias: 'agent_e2e',
    },
  },
  accounts: {
    e2e: {
      display_name: 'E2E',
      env: { CLAUDE_CONFIG_DIR: E2E_CLAUDE_DIR },
    },
  },
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

const env = {
  ...process.env,
  CPC_DATA_DIR: DATA_DIR,
  CPC_LOGS_DIR: LOGS_DIR,
  CPC_SECRETS_DIR: SECRETS_DIR,
  CPC_CONFIG_PATH: CONFIG_PATH,
  CPC_E2E: '1',
  PYTHONUNBUFFERED: '1',
}

// Single-stage spawn: resolve the python binary up front so SIGTERM reaches
// uvicorn directly. `conda run` adds an opaque shim layer that swallows
// signals (= orphans uvicorn on teardown), so we bypass it.
//
// Resolution order:
//   1. $CPC_E2E_PYTHON                       (= explicit override)
//   2. $CONDA_PREFIX_PWA_CLIENT/bin/python3  (= conda env path env override)
//   3. miniforge3/envs/pwa-client/bin/python3.11 / python3 (= conventional)
//   4. `python3` on PATH                     (= last resort)
const candidates = [
  process.env.CPC_E2E_PYTHON,
  process.env.CONDA_PREFIX_PWA_CLIENT && `${process.env.CONDA_PREFIX_PWA_CLIENT}/bin/python3`,
  `${homedir()}/miniforge3/envs/pwa-client/bin/python3.11`,
  `${homedir()}/miniforge3/envs/pwa-client/bin/python3`,
  `${homedir()}/miniconda3/envs/pwa-client/bin/python3`,
  `${homedir()}/anaconda3/envs/pwa-client/bin/python3`,
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

let shuttingDown = false
const shutdown = (sig) => {
  if (shuttingDown) return
  shuttingDown = true
  try { child.kill(sig) } catch (_) { /* benign: child already gone */ }
  // hard fallback if uvicorn ignores SIGTERM (= during long shutdown hooks)
  setTimeout(() => { try { child.kill('SIGKILL') } catch (_) {} }, 5_000).unref()
}
process.on('SIGINT', () => shutdown('SIGINT'))
process.on('SIGTERM', () => shutdown('SIGTERM'))
process.on('exit', () => { try { child.kill('SIGTERM') } catch (_) {} })

child.on('exit', (code, sig) => {
  process.exitCode = code ?? (sig ? 1 : 0)
})
