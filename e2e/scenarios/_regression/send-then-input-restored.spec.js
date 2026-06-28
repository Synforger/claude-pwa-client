// Regression for the post-send input residue cluster (= 2026-06-24 fix
// 6bd5b1f, "cancel SEND_TIMEOUT watcher when SSE confirms the user
// message"). Symptom: after a successful send the input box keeps the typed
// text for several seconds before clearing, because the SEND_TIMEOUT
// watcher's late fallback re-stamped sendFailedText into the input even on
// happy-path delivery.
//
// Scenario shape:
//   1. Seed an empty session.
//   2. Open the PWA.
//   3. Type a fresh prompt + send.
//   4. Assert the input field is cleared immediately (= the optimistic
//      clear path runs on send).
//   5. Wait for reconcile to confirm the bubble.
//   6. Wait > the original 15s SEND_TIMEOUT window. Assert the input is
//      still empty (= the watcher was cancelled, no zombie restore).

import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2esend01'
const TEXT = 'send clears me ' + Math.floor(performance.now() % 1e6)

test.describe('regression: send-then-input-restored', () => {
  test('input clears on send and stays clear after the timeout window', async ({ page, request }) => {
    await seedSession(request, 'e2e-send-empty')

    await openClient(page, { sid: SID })

    const input = page.locator('[data-testid=chat-input]')
    await input.fill(TEXT)
    await page.locator('[data-testid=chat-send-button]').click()

    // (4) Optimistic clear: the input drops the text right away.
    await expect(input).toHaveValue('', { timeout: 2_000 })

    // (5) Reconcile lands.
    const confirmed = page.locator(
      '[data-testid=message-bubble-user][data-cpc-optimistic="0"]',
    )
    await expect(confirmed).toHaveCount(1, { timeout: 20_000 })

    // (6) Past the historical 15s watcher window. With the fix in place the
    // input must still be empty - no sendFailedText resurrection.
    await page.waitForTimeout(16_000)
    await expect(input).toHaveValue('')
    // And no failure note materialised either.
    await expect(page.locator('.send-failed-note')).toHaveCount(0)
  })
})
