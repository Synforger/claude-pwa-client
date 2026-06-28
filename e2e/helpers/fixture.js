// Fixture loaders for playwright scenarios. Read a JSONL of claude events +
// its sibling .meta.json, POST /debug/e2e/seed (ADR-020). Scenarios that need
// late arrivals append directly to the seeded JSONL on disk — backend watcher
// tails it like a real session.
import { readFileSync, existsSync, appendFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const E2E_ROOT = resolve(__dirname, '..')
const SESSIONS_DIR = resolve(E2E_ROOT, 'fixtures', 'sessions')

export function loadFixture(name) {
  const jsonl = join(SESSIONS_DIR, `${name}.jsonl`)
  const meta = join(SESSIONS_DIR, `${name}.meta.json`)
  if (!existsSync(jsonl) || !existsSync(meta)) {
    throw new Error(`fixture missing: ${name} (need ${name}.jsonl + ${name}.meta.json)`)
  }
  const events = readFileSync(jsonl, 'utf-8').split('\n').filter(Boolean).map((l) => JSON.parse(l))
  const metadata = JSON.parse(readFileSync(meta, 'utf-8'))
  return { ...metadata, jsonl_events: events }
}

export async function seedSession(request, name) {
  const body = loadFixture(name)
  const res = await request.post('/debug/e2e/seed', { data: body })
  if (!res.ok()) {
    throw new Error(`/debug/e2e/seed failed for ${name}: ${res.status()} ${await res.text()}`)
  }
  return res.json()
}

// Append an event to a seeded session's JSONL on disk. Use this for "late
// arrival" scenarios — the backend watcher picks it up on its next tail tick.
export function appendEvent(jsonlPath, event) {
  appendFileSync(jsonlPath, JSON.stringify(event) + '\n', { encoding: 'utf-8' })
}
