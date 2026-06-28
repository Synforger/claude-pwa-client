// Seeds the canonical fixture set into the running backend (= POST
// /debug/e2e/seed, ADR-020) before any spec runs. Scenarios add more sessions
// at will via seedSession().
import { readdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { request as createRequest } from '@playwright/test'
import { loadFixture } from './fixture.js'

const __dirname = dirname(fileURLToPath(import.meta.url))
const SESSIONS_DIR = resolve(__dirname, '..', 'fixtures', 'sessions')

export default async function globalSetup(config) {
  const baseURL = config.projects[0]?.use?.baseURL || config.use?.baseURL
  const ctx = await createRequest.newContext({ baseURL })
  try {
    // Mirror every <name>.jsonl that has a matching <name>.meta.json — meta
    // files alone never seed.
    const names = new Set(
      readdirSync(SESSIONS_DIR)
        .filter((n) => n.endsWith('.meta.json'))
        .map((n) => n.replace(/\.meta\.json$/, '')),
    )
    for (const name of names) {
      const body = loadFixture(name)
      const res = await ctx.post('/debug/e2e/seed', { data: body })
      if (!res.ok()) {
        throw new Error(`globalSetup seed failed for ${name}: ${res.status()} ${await res.text()}`)
      }
    }
  } finally {
    await ctx.dispose()
  }
}
