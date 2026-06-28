// Contract: full page refresh hydrates chat from localStorage AND reconnects
// SSE so newly-arrived events show up after the reload too (= ADR-013
// "iOS 7-day storage cap耐性" + offset-based SSE replay).

import { test, expect } from '@playwright/test'
import { seedSession, appendEvent } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2erefresh'

test.describe('contract: refresh syncs chat', () => {
  test('reload picks up events that landed after the cache was last written', async ({ page, request }) => {
    const seeded = await request.post('/debug/e2e/seed', {
      data: {
        sid: SID,
        agent_id: 'agent_e2e',
        account_id: 'e2e',
        title: 'refresh sync',
        jsonl_events: [
          { type: 'user', uuid: 'u-pre-001',
            message: { role: 'user', content: 'pre-refresh' },
            timestamp: new Date(0).toISOString() },
        ],
      },
    }).then((r) => r.json())

    await openClient(page, { sid: SID })

    await expect(page.locator('[data-testid=message-bubble-user]')).toHaveCount(1)
    await expect(page.locator('[data-testid=message-bubble-user]')).toContainText('pre-refresh')

    // Append a new event while the tab is open (= regular tail path) so the
    // localStorage cache catches it.
    appendEvent(seeded.jsonl_path, {
      type: 'user', uuid: 'u-mid-001',
      message: { role: 'user', content: 'mid-life' },
      timestamp: new Date(0).toISOString(),
    })
    await expect(page.locator('[data-testid=message-bubble-user]')).toHaveCount(2, { timeout: 10_000 })

    // Now reload; both messages have to survive the rehydrate.
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible' })
    await page.waitForTimeout(1500)
    await expect(page.locator('[data-testid=message-bubble-user]')).toHaveCount(2)

    // And an event that lands *after* the reload also delivers — the new
    // EventSource opens with ?from=offsets so the watcher streams it.
    appendEvent(seeded.jsonl_path, {
      type: 'user', uuid: 'u-post-001',
      message: { role: 'user', content: 'post-refresh' },
      timestamp: new Date(0).toISOString(),
    })
    await expect(page.locator('[data-testid=message-bubble-user]')).toHaveCount(3, { timeout: 10_000 })
  })
})
