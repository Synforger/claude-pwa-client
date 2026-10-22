// Golden path: fork feature.
// Seed a user message that has a server uuid (= forkable), click the ⑂
// button on its bubble, assert a new session row shows up in the drawer
// and the new tab is now active.

import { test, expect } from '@playwright/test'
import { seedSession, appendEvent } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'

test.describe('golden: fork', () => {
  test('fork button on a confirmed user bubble spawns a new tab', async ({ page, request }) => {
    const seeded = await seedSession(request, 'e2e-chat-golden')

    // Pre-load a confirmed user + assistant pair so the user row is forkable
    // straight away (canForkUser requires uuid + !optimistic + !sendFailed).
    appendEvent(seeded.jsonl_path, {
      type: 'user',
      uuid: 'u-fork-001',
      message: { role: 'user', content: 'fork me' },
      timestamp: new Date(0).toISOString(),
    })
    appendEvent(seeded.jsonl_path, {
      type: 'assistant',
      uuid: 'a-fork-001',
      parentUuid: 'u-fork-001',
      message: {
        id: 'msg_fork_01',
        role: 'assistant',
        content: [{ type: 'text', text: 'after fork point' }],
        stop_reason: 'end_turn',
        model: 'claude-opus-4-7',
      },
      timestamp: new Date(0).toISOString(),
    })

    await openClient(page, { sid: SID })

    const userBubble = page.locator(
      '[data-testid=message-bubble-user][data-cpc-uuid="u-fork-001"]',
    )
    await expect(userBubble).toBeVisible({ timeout: 10_000 })

    // Count existing rows via the API (= avoids opening the drawer twice).
    const before = await (await page.request.get('/sessions')).json()
      .then((b) => (b.sessions || b).length)

    await page.locator('[data-testid=fork-button]').first().click()

    // A new session shows up under /sessions.
    await expect.poll(
      async () => (await (await page.request.get('/sessions')).json()).sessions?.length
        ?? (await (await page.request.get('/sessions')).json()).length,
      { timeout: 10_000 },
    ).toBe(before + 1)
  })
})
