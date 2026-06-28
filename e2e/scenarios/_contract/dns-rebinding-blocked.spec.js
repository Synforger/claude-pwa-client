// Contract: ADR-012 DNS rebinding defence on /debug/* - loopback peer
// alone is not enough; the Host header has to be on the allowlist.

import { test, expect } from '@playwright/test'

test.describe('contract: DNS rebinding blocked', () => {
  test('/debug/state 200 from loopback, 403 with a foreign Host', async ({ request }) => {
    const allowed = await request.get('/debug/state')
    expect(allowed.status()).toBe(200)

    const rebound = await request.get('/debug/state', { headers: { host: 'attacker.example.com' } })
    expect(rebound.status()).toBe(403)
    // The other readers should also reject.
    const reboundLog = await request.get('/debug/log', { headers: { host: 'evil:8765' } })
    expect(reboundLog.status()).toBe(403)
  })
})
