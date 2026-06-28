// Regression for the duplicate user-bubble cluster (= 2026-06-23 fix chain
// 5826538 -> 6160f71 -> 8c6dcf9, "server-of-truth user message reconciliation
// to kill resurface ghosts").
//
// Bug shape: the optimistic user bubble that frontend pushes on send and the
// server-confirmed user_message event that arrives a moment later are not
// reconciled to a single row, leaving two bubbles for one message.
//
// Scenario shape (post-ADR-021):
//   1. Seed an empty session via /debug/e2e/seed.
//   2. Open the PWA targeting that session.
//   3. Type a fresh prompt + press send. Two things now race:
//        - frontend pushes an optimistic user bubble immediately.
//        - backend's e2e fast path (= ADR-021) appends a server-stamped
//          user row to the bound JSONL, the watcher tails it, and the SSE
//          pump delivers user_message to the same client.
//   4. Wait until the bubble's data-cpc-optimistic flips to "0" (= reconciled).
//   5. Assert there is exactly ONE user bubble, with the typed text.

import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2erecon01'
const PROMPT = 'reconcile probe ' + Math.floor(performance.now() % 1e6)

test.describe('regression: reconcile-no-duplicate', () => {
  test('optimistic + server-confirmed collapse into a single user bubble', async ({ page, request }) => {
    // Reseed in case a prior spec touched the JSONL on disk.
    const seeded = await seedSession(request, 'e2e-reconcile-empty')
    expect(seeded.sid).toBe(SID)

    await openClient(page, { sid: SID })

    await page.locator('[data-testid=chat-input]').fill(PROMPT)
    await page.locator('[data-testid=chat-send-button]').click()

    // Optimistic should appear (= snapshot of pre-reconcile state).
    await expect(page.locator('[data-testid=message-bubble-user]')).toHaveCount(1)

    // Reconcile lands: the bubble flips from optimistic to confirmed
    // (data-cpc-optimistic="0" and a server uuid present).
    const confirmed = page.locator(
      '[data-testid=message-bubble-user][data-cpc-optimistic="0"]',
    )
    await expect(confirmed).toHaveCount(1, { timeout: 10_000 })
    await expect(confirmed).not.toHaveAttribute('data-cpc-uuid', '')

    // No duplicate after reconcile: still exactly one user bubble, with the
    // typed prompt as its text content.
    const allUserBubbles = page.locator('[data-testid=message-bubble-user]')
    await expect(allUserBubbles).toHaveCount(1)
    await expect(allUserBubbles).toContainText(PROMPT)
  })
})
