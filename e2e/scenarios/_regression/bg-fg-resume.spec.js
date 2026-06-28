// Regression for the bg→fg ghost-message cluster (= 2026-06-22 fix chain
// 9e94f42 + 6099802, "flush localStorage cache + reconnect SSE on bg→fg
// transition" / "tighten cache flush so chat does not roll back on app
// switch").
//
// Bug shape: putting the PWA in the background (= iOS suspends the JS
// context, EventSource silently stalls) and bringing it back leaves the chat
// view stale - new events that arrived while hidden never get replayed and
// the localStorage rehydrate uses an old snapshot.
//
// Scenario shape:
//   1. Seed a session with one baseline user+assistant exchange.
//   2. Open the PWA, confirm the baseline bubble is on screen.
//   3. Simulate going to the background (= visibilitychange hidden +
//      pagehide). The transport/lifecycle handlers should flush offsets +
//      stop the live SSE / Views WS.
//   4. While hidden, append a brand new user_message to the bound JSONL on
//      disk - this is the "event that arrived while we were away".
//   5. Simulate coming back (= visibilitychange visible). lifecycle.js
//      should bump the SSE reconnect so the new event is delivered.
//   6. Assert the new bubble shows up with its server uuid - no ghost
//      (= text-only, no uuid) variant lingers.

import { test, expect } from '@playwright/test'
import { seedSession, appendEvent } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2ebgfg01'
const LATE_UUID = 'u-bgfg-late'
const LATE_TEXT = 'arrived while hidden ' + Math.floor(performance.now() % 1e6)

async function setVisibility(page, state) {
  await page.evaluate((v) => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => v })
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => v === 'hidden' })
    document.dispatchEvent(new Event('visibilitychange'))
    if (v === 'hidden') {
      window.dispatchEvent(new Event('pagehide'))
    } else {
      window.dispatchEvent(new Event('pageshow'))
    }
  }, state)
}

test.describe('regression: bg-fg-resume', () => {
  test('messages that arrive while hidden are replayed on resume', async ({ page, request }) => {
    const seeded = await seedSession(request, 'e2e-bg-fg')
    expect(seeded.sid).toBe(SID)

    await openClient(page, { sid: SID })

    // Baseline visible before we go away.
    await expect(page.locator('[data-testid=message-bubble-user]')).toHaveCount(1)

    // (3) Go to the background.
    await setVisibility(page, 'hidden')

    // (4) New event lands on disk while we are away.
    appendEvent(seeded.jsonl_path, {
      type: 'user',
      uuid: LATE_UUID,
      message: { role: 'user', content: LATE_TEXT },
      timestamp: new Date(0).toISOString(),
    })

    // Give the watcher a moment to notice while still hidden — we should NOT
    // be receiving it yet (SSE is stopped while hidden) but the file is on
    // disk waiting for the resume reconnect.
    await page.waitForTimeout(500)

    // (5) Come back.
    await setVisibility(page, 'visible')

    // (6) The late event materialises as a real bubble (uuid present, not
    // optimistic). No ghost duplicate.
    const lateBubble = page.locator(
      `[data-testid=message-bubble-user][data-cpc-uuid="${LATE_UUID}"]`,
    )
    await expect(lateBubble).toHaveCount(1, { timeout: 10_000 })
    await expect(lateBubble).toContainText(LATE_TEXT)

    // Two user bubbles total (= baseline + late), neither optimistic.
    const allUsers = page.locator('[data-testid=message-bubble-user]')
    await expect(allUsers).toHaveCount(2)
    const optimistics = page.locator(
      '[data-testid=message-bubble-user][data-cpc-optimistic="1"]',
    )
    await expect(optimistics).toHaveCount(0)
  })
})
