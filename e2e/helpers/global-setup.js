// Runs once before all playwright workers start. The webServer hook has
// already booted the backend (or KEEP_BACKEND points us at a live one); here
// we seed JSONL + replay fixtures into the runtime data dir so scenarios can
// open them like real chat history.
import { mkdirSync, copyFileSync, readdirSync, existsSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const E2E_ROOT = resolve(__dirname, '..')
const RUNTIME = resolve(E2E_ROOT, 'fixtures', '_runtime')
const RUNTIME_JSONL = resolve(RUNTIME, 'jsonl')

export default async function globalSetup() {
  // Mirror fixtures/sessions/<sid>.jsonl into _runtime/jsonl/ so the backend
  // watcher picks them up. Each fixture file is one full claude session in
  // claude's native JSONL shape (= one event per line, server-stamped uuids).
  const srcDir = resolve(E2E_ROOT, 'fixtures', 'sessions')
  if (!existsSync(srcDir)) return
  mkdirSync(RUNTIME_JSONL, { recursive: true })
  for (const name of readdirSync(srcDir)) {
    if (!name.endsWith('.jsonl')) continue
    copyFileSync(join(srcDir, name), join(RUNTIME_JSONL, name))
  }
}
