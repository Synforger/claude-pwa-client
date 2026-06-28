// Minimal smoke: confirm the test-mode backend booted, /healthz answers 200,
// and the unified SSE stream opens without auth. If this scenario fails the
// rest of the suite has no chance.
import { test, expect } from '@playwright/test'

test.describe('smoke', () => {
  test('healthz responds 200', async ({ request }) => {
    const res = await request.get('/healthz')
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.ok).toBe(true)
  })

  test('debug/state is reachable from loopback', async ({ request }) => {
    const res = await request.get('/debug/state')
    expect(res.status()).toBe(200)
  })

  test('debug/state rejects mismatched Host header', async ({ request }) => {
    const res = await request.get('/debug/state', { headers: { host: 'attacker.example.com' } })
    expect(res.status()).toBe(403)
  })

  test('seeded fixture session is visible via /sessions', async ({ request }) => {
    // globalSetup seeded e2e-chat-basic before any spec ran.
    const res = await request.get('/sessions')
    expect(res.status()).toBe(200)
    const body = await res.json()
    const sids = (body.sessions || body).map((s) => s.id || s.sid)
    expect(sids).toContain('ses_e2echatbas')
  })
})
