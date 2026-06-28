// Golden path: chat feature.
// send -> user bubble (server confirmed) -> assistant bubble lands when the
// server appends an assistant row -> history persists across a reload.

import { test, expect } from '@playwright/test'
import { seedSession, appendEvent } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'

test.describe('golden: chat', () => {
  test('send + receive + history persistence', async ({ page, request }) => {
    const seeded = await seedSession(request, 'e2e-chat-golden')

    await openClient(page, { sid: SID })

    // The shared ses_e2echatgld is reseeded across many specs; localStorage
    // can carry over messages from a previous spec. Clear the rehydrate
    // before sending so the bubble we assert on is the one we just typed.
    await page.evaluate(() => {
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i)
        if (k && k.startsWith('cpc.messages.')) localStorage.removeItem(k)
      }
    })
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible' })
    await page.waitForTimeout(1500)

    const prompt = 'golden chat ' + Math.floor(performance.now() % 1e6)
    await page.locator('[data-testid=chat-input]').fill(prompt)
    await page.locator('[data-testid=chat-send-button]').click()

    // Server-confirmed user bubble lands.
    const userBubble = page.locator(
      '[data-testid=message-bubble-user][data-cpc-optimistic="0"]',
    )
    await expect(userBubble).toHaveCount(1, { timeout: 15_000 })
    await expect(userBubble).toContainText(prompt)

    // Server appends an assistant reply; it should appear in the chat.
    const replyText = 'golden assistant reply ' + Math.floor(performance.now() % 1e6)
    appendEvent(seeded.jsonl_path, {
      type: 'assistant',
      uuid: 'a-gold-' + Math.floor(performance.now() % 1e6).toString(16),
      parentUuid: await userBubble.getAttribute('data-cpc-uuid'),
      message: {
        id: 'msg_gold_01',
        role: 'assistant',
        content: [{ type: 'text', text: replyText }],
        stop_reason: 'end_turn',
        model: 'claude-opus-4-7',
        usage: { input_tokens: 3, output_tokens: 4 },
      },
      timestamp: new Date(0).toISOString(),
    })

    const assistantBubble = page.locator('[data-testid=message-bubble-agent]')
    await expect(assistantBubble).toHaveCount(1, { timeout: 10_000 })
    await expect(assistantBubble).toContainText(replyText)

    // Reload — both messages persist via localStorage rehydrate.
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible' })
    await page.waitForTimeout(1500)
    await expect(page.locator('[data-testid=message-bubble-user]')).toHaveCount(1)
    await expect(page.locator('[data-testid=message-bubble-agent]')).toHaveCount(1)
    await expect(page.locator('[data-testid=message-bubble-user]')).toContainText(prompt)
    await expect(page.locator('[data-testid=message-bubble-agent]')).toContainText(replyText)
  })
})
