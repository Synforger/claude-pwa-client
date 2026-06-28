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
})
