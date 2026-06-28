#!/usr/bin/env node
// Coverage gate: every feature category from the W4 plan must have at least
// one matching golden spec. Run after `npm test`; CI calls this directly.
//
// The feature list mirrors `05-w4-e2e.md` § golden path scenario の書き方.
// Keep it in sync when the inventory grows.
import { readdirSync, existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(__dirname, '..')
const GOLDEN_DIR = resolve(ROOT, 'scenarios', '_golden')

const REQUIRED = [
  'chat',
  'session-drawer',
  'file-tree',
  'file-preview',
  'tasks',
  'subagents',
  'plan-approval',
  'ask-user-question',
  'push-notify',
  'attachments',
  'fork',
  'status-bar',
  'screenshare',
  'ios-native',
  'terminal',
]

if (!existsSync(GOLDEN_DIR)) {
  console.error(`golden dir missing: ${GOLDEN_DIR}`)
  process.exit(2)
}

const present = new Set(
  readdirSync(GOLDEN_DIR)
    .filter((n) => n.endsWith('.spec.js'))
    .map((n) => n.replace(/\.spec\.js$/, '')),
)

const missing = REQUIRED.filter((name) => !present.has(name))
const extra = [...present].filter((name) => !REQUIRED.includes(name))

if (missing.length === 0) {
  console.log(`coverage: ${REQUIRED.length}/${REQUIRED.length} golden specs present`)
  if (extra.length) console.log(`coverage: extra (not on the required list): ${extra.join(', ')}`)
  process.exit(0)
}

console.error('coverage: missing golden specs for the following features:')
for (const name of missing) console.error(`  - ${name}`)
process.exit(1)
