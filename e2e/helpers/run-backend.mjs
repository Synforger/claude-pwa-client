#!/usr/bin/env node
// playwright webServer launcher.
// Boots the v2 backend on port 18765 (≠ prod 8765 LaunchAgent) with a tmp
// data dir + minimal config + stub claude binary so the operator's real chat
// history is never touched. SIGINT / SIGTERM tear the child down cleanly.
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync, rmSync, existsSync } from 'node:fs'
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
    e2e: { display_name: 'E2E', env: {} },
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

const useConda = !process.env.CPC_E2E_NO_CONDA
const args = useConda
  ? ['run', '--no-capture-output', '-n', 'pwa-client',
     'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', PORT]
  : ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', PORT]
const cmd = useConda ? 'conda' : 'python3'

const child = spawn(cmd, args, {
  cwd: REPO_ROOT,
  env,
  stdio: ['ignore', 'inherit', 'inherit'],
})

const shutdown = (sig) => {
  try { child.kill(sig) } catch (_) { /* benign: child already gone */ }
}
process.on('SIGINT', () => shutdown('SIGINT'))
process.on('SIGTERM', () => shutdown('SIGTERM'))

child.on('exit', (code, sig) => {
  process.exitCode = code ?? (sig ? 1 : 0)
})
