// Golden path: push-notify feature.
// The PWA fetches the server's VAPID public key from /push/vapid-public-key.
// This proves the wiring; the actual PushManager.subscribe call needs a
// real service worker + browser permission and is covered by frontend
// unit tests on usePushSubscription.

import { test, expect } from '@playwright/test'

test.describe('golden: push-notify', () => {
  test('VAPID public key endpoint serves a key', async ({ request }) => {
    const res = await request.get('/push/vapid-public-key')
    expect(res.status()).toBe(200)
    const body = await res.json()
    // Server-side stub writes a placeholder key in the e2e config; the
    // shape is what matters - a non-empty string under the documented key.
    expect(typeof body.public_key).toBe('string')
    expect(body.public_key.length).toBeGreaterThan(10)
  })
})
