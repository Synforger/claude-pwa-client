// Starts test backends of their own, next to the one Playwright starts, for the scenarios in which two machines talk.
// Each has its own port, runtime folder and tmux socket (= `run-backend.mjs` wipes its runtime folder at its start and
// kills its tmux server at its end, so two backends must never share them), and names the other as the machine it may
// message. Both run on this machine, so each reaches the other at 127.0.0.1.
import { spawn } from 'node:child_process'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { request as createRequest } from '@playwright/test'

const __dirname = dirname(fileURLToPath(import.meta.url))
const RUN_BACKEND = resolve(__dirname, 'run-backend.mjs')
const RUNTIME_ROOT = resolve(__dirname, '..', 'fixtures', '_runtime', 'peers')
const READY_TIMEOUT_MS = 60_000
const EXIT_TIMEOUT_MS = 20_000

const sleep = (ms) => new Promise((done) => setTimeout(done, ms))

async function answers(baseURL) {
  try {
    return (await fetch(`${baseURL}/healthz`, { signal: AbortSignal.timeout(2_000) })).ok
  } catch (_) {
    return false
  }
}

// One backend of a pair. `peers` is the other machine: {name, port}. `checkIntervalSec` is how often its watch looks
// at that machine (= five minutes in production). `extraEnv` is added to what `run-backend.mjs` is started with (= a
// scenario that needs a backend of its own, such as one with an API tab, uses this class with no peers).
export class PeerBackend {
  constructor({ name, port, peers = [], checkIntervalSec = 30, extraEnv = {} }) {
    this.name = name
    this.port = port
    this.baseURL = `http://127.0.0.1:${port}`
    this.runtimeDir = resolve(RUNTIME_ROOT, name)
    this.dataDir = resolve(this.runtimeDir, 'data')
    this.peers = Object.fromEntries(
      peers.map((peer) => [peer.name, { url: `http://127.0.0.1:${peer.port}`, address: '127.0.0.1' }]))
    this.checkIntervalSec = checkIntervalSec
    this.extraEnv = extraEnv
    this.child = null
    this.api = null
  }

  async start({ reuse = false } = {}) {
    this.child = spawn(process.execPath, [RUN_BACKEND], {
      env: {
        ...process.env,
        CPC_E2E_PORT: String(this.port),
        CPC_E2E_RUNTIME_DIR: this.runtimeDir,
        CPC_E2E_REUSE_RUNTIME: reuse ? '1' : '0',
        CPC_E2E_PEERS: JSON.stringify(this.peers),
        CPC_TMUX_SOCKET: `cpc-e2e-${this.port}`,
        CPC_PEER_CHECK_INTERVAL_SEC: String(this.checkIntervalSec),
        ...this.extraEnv,
      },
      stdio: ['ignore', 'inherit', 'inherit'],
    })
    const deadline = Date.now() + READY_TIMEOUT_MS
    while (!(await answers(this.baseURL))) {
      if (Date.now() > deadline) throw new Error(`${this.name}: the backend did not answer on ${this.baseURL}`)
      await sleep(500)
    }
    this.api = await createRequest.newContext({ baseURL: this.baseURL })
  }

  // Stop the backend the way Playwright's own teardown does (= SIGTERM to the launcher, which stops uvicorn).
  async stop() {
    if (this.api) await this.api.dispose()
    this.api = null
    const child = this.child
    if (!child) return
    this.child = null
    const exited = new Promise((done) => child.once('exit', done))
    child.kill('SIGTERM')
    await Promise.race([exited, sleep(EXIT_TIMEOUT_MS)])
    const deadline = Date.now() + EXIT_TIMEOUT_MS
    while (await answers(this.baseURL)) {
      if (Date.now() > deadline) throw new Error(`${this.name}: the backend still answers after it was stopped`)
      await sleep(250)
    }
  }
}
