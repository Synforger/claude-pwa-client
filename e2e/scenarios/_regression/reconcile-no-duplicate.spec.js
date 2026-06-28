// Regression for the duplicate user-bubble cluster (= 2026-06-23 fix chain
// 5826538 -> 6160f71 -> 8c6dcf9, "server-of-truth user message reconciliation
// to kill resurface ghosts").
//
// Bug shape: the optimistic user bubble that frontend pushes on send and the
// server-confirmed user_message event that arrives a moment later are not
// reconciled to a single row, leaving two bubbles for one message.
//
// Scenario shape:
//   1. Seed an empty session via /debug/e2e/seed (ADR-020).
//   2. Open the PWA targeting that session.
//   3. Type a fresh prompt + press send -> assert the optimistic bubble
//      appears with data-cpc-optimistic="1" and no uuid.
//   4. Append a user_message event to the seeded JSONL on disk - the backend
//      watcher tails it and the unified SSE delivers a user_message to the
//      client; reconcileUserMessage should eat the optimistic in place.
//   5. Wait for the bubble to flip to data-cpc-optimistic="0" with a uuid.
//   6. Assert there is exactly ONE user bubble, with the typed text.
//
// We do NOT wait for /chat's claude turn to complete - in test mode
// claude_path is /usr/bin/true so the assistant side never speaks. The
// regression is entirely on the user side of the reconciliation.

import { test, expect } from '@playwright/test'
import { seedSession, appendEvent } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2erecon01'
const PROMPT = 'reconcile probe ' + Math.floor(performance.now() % 1e6)
const SERVER_UUID = 'u-recon-' + Math.floor(performance.now() % 1e6).toString(16)

test.describe('regression: reconcile-no-duplicate', () => {
  test('optimistic + server-confirmed collapse into a single user bubble', async ({ page, request }) => {
    // globalSetup already seeded the fixture; reseed in case a prior spec
    // mutated it, so the JSONL on disk is empty at the start of this run.
    const seeded = await seedSession(request, 'e2e-reconcile-empty')
    expect(seeded.sid).toBe(SID)

    await openClient(page, { sid: SID })

    await page.locator('[data-testid=chat-input]').fill(PROMPT)
    await page.locator('[data-testid=chat-send-button]').click()

    // (3) Optimistic appears.
    const optimistic = page.locator('[data-testid=message-bubble-user][data-cpc-optimistic="1"]')
    await expect(optimistic).toHaveCount(1)

    // (4) Inject a server-confirmed user_message with a matching text. The
    // exact text must match so reconcileUserMessage's text equality path
    // claims the optimistic instead of appending alongside it.
    appendEvent(seeded.jsonl_path, {
      type: 'user',
      uuid: SERVER_UUID,
      message: { role: 'user', content: PROMPT },
      timestamp: new Date(0).toISOString(),
    })

    // (5) Bubble flips to confirmed.
    const confirmed = page.locator(`[data-testid=message-bubble-user][data-cpc-uuid="${SERVER_UUID}"]`)
    await expect(confirmed).toHaveCount(1, { timeout: 10_000 })
    await expect(confirmed).toHaveAttribute('data-cpc-optimistic', '0')

    // (6) No duplicate: exactly one user bubble across the whole list.
    const allUserBubbles = page.locator('[data-testid=message-bubble-user]')
    await expect(allUserBubbles).toHaveCount(1)
    await expect(allUserBubbles).toContainText(PROMPT)
  })
})
