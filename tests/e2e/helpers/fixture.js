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

// Mark a seeded session as one whose Claude is working, or put it back. While it is working, a
// send from the screen writes what Claude writes for a message typed mid-task: a queue-operation
// row and no user row. The scenario writes the hand-over (`queuedHandOver`) when it wants Claude
// to take the message.
export async function setWorking(request, sid, working) {
  const res = await request.post(`/debug/e2e/working/${sid}`, { data: { working } })
  if (!res.ok()) throw new Error(`/debug/e2e/working failed: ${res.status()} ${await res.text()}`)
}

// The rows Claude writes when it takes a queued message between two steps. The attachment row
// carries the time the message was typed, though it is written after rows that are later in time.
export function queuedHandOver(jsonlPath, { uuid, text, typedAt }) {
  appendEvent(jsonlPath, { type: 'queue-operation', operation: 'remove', timestamp: new Date().toISOString(), content: text })
  appendEvent(jsonlPath, {
    type: 'attachment', uuid, isSidechain: false, timestamp: typedAt,
    attachment: { type: 'queued_command', prompt: text, commandMode: 'prompt', origin: { kind: 'human' }, humanTurn: true, timestamp: typedAt },
  })
}

// Make the backend forget which send each waiting message came from, as it does by itself a
// minute after a send: a message Claude takes later than that arrives with no send id.
export async function forgetSends(request) {
  const res = await request.post('/debug/e2e/forget-sends')
  if (!res.ok()) throw new Error(`/debug/e2e/forget-sends failed: ${res.status()} ${await res.text()}`)
}
