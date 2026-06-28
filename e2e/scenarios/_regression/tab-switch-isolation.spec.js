// Regression for the cross-tab message leak (= 2026-06-24 cluster around
// 6bd5b1f / 45f4aee / e2122a6, "tabs never cross-pollute"). Symptom: a
// message typed into session A briefly surfaces in session B's chat after a
// tab switch, because state was keyed on "the current sid" instead of being
// owned per-sid.
//
// Scenario shape:
//   1. Seed two empty sessions, A and B.
//   2. Open the PWA on A. Type and send "msg-in-A".
//   3. Wait for it to land server-confirmed (= reconciled).
//   4. Switch to B via the drawer.
//   5. Assert B's chat shows zero user bubbles — the A message must not be
//      visible from B.
//   6. Switch back to A. The "msg-in-A" bubble is still there with its
//      server uuid; it never lost the carrier session.

import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID_A = 'ses_e2etab0a'
const SID_B = 'ses_e2etab0b'
const TEXT_A = 'tab-isolation A ' + Math.floor(performance.now() % 1e6)

test.describe('regression: tab-switch-isolation', () => {
  test('messages stay in the tab they were sent from', async ({ page, request }) => {
    await seedSession(request, 'e2e-tab-a')
    await seedSession(request, 'e2e-tab-b')

    await openClient(page, { sid: SID_A })

    // (2) Send the message in A.
    await page.locator('[data-testid=chat-input]').fill(TEXT_A)
    await page.locator('[data-testid=chat-send-button]').click()

    // (3) Wait for reconcile to confirm it in A.
    const confirmedInA = page.locator(
      '[data-testid=message-bubble-user][data-cpc-optimistic="0"]',
    )
    await expect(confirmedInA).toHaveCount(1, { timeout: 10_000 })
    await expect(confirmedInA).toContainText(TEXT_A)

    // (4) Switch to B via the drawer.
    await page.locator('[data-testid=drawer-toggle]').click()
    await page.locator(`[data-testid=session-list-item][data-cpc-sid="${SID_B}"] [data-testid=session-list-item-select]`).click()

    // (5) B carries no user bubbles. The cross-pollution bug would surface
    // A's message here.
    await expect(
      page.locator('[data-testid=message-bubble-user]'),
    ).toHaveCount(0)

    // (6) Switch back. A's bubble is still there.
    await page.locator('[data-testid=drawer-toggle]').click()
    await page.locator(`[data-testid=session-list-item][data-cpc-sid="${SID_A}"] [data-testid=session-list-item-select]`).click()
    const back = page.locator('[data-testid=message-bubble-user]')
    await expect(back).toHaveCount(1)
    await expect(back).toContainText(TEXT_A)
  })
})
