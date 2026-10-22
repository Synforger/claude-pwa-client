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
      timestamp: new Date().toISOString(),
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

// The input grows with what is typed and stops at three lines, so the reply above stays
// readable. Past that a small toggle on its top edge lets it grow to six lines, still in the page's flow.
test.describe('golden: chat input size', () => {
  const input = '[data-testid=chat-input]'
  const toggle = '[data-testid=chat-input-size-toggle]'
  const lines = (n) => Array.from({ length: n }, (_, i) => `line ${i + 1}`).join('\n')
  const height = (page) => page.locator(input).evaluate((el) => el.getBoundingClientRect().height)
  // A line limit, read from the page's own styles (= n lines + padding + border).
  const cap = (page, n) => page.locator(input).evaluate((el, n) => {
    const cs = getComputedStyle(el)
    const px = (v) => parseFloat(v) || 0
    return px(cs.lineHeight) * n + px(cs.paddingTop) + px(cs.paddingBottom)
      + px(cs.borderTopWidth) + px(cs.borderBottomWidth)
  }, n)
  const overflows = (page) => page.locator(input).evaluate((el) => el.scrollHeight > el.clientHeight)

  test('grows with the text and stops at three lines', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })

    const natural = await height(page)
    const folded = await cap(page, 3)

    await page.locator(input).fill('one line')
    expect(await height(page)).toBeCloseTo(natural, 0)
    await expect(page.locator(toggle)).toHaveCount(0)

    await page.locator(input).fill(lines(3))
    expect(await height(page)).toBeCloseTo(Math.max(folded, natural), 0)
    await expect(page.locator(toggle)).toHaveCount(0)
    const areaHeight = () => page.locator('.inputarea').evaluate((el) => el.getBoundingClientRect().height)
    const withoutToggle = await areaHeight()

    await page.locator(input).fill(lines(4))
    expect(await height(page)).toBeCloseTo(Math.max(folded, natural), 0)
    await expect(page.locator(toggle)).toBeVisible()
    // The toggle sits on the top edge and takes no line of its own: the input area does not grow.
    expect(await areaHeight()).toBeCloseTo(withoutToggle, 0)
    await expect(page.locator(toggle)).toHaveAttribute('aria-expanded', 'false')
    // The fourth line is there, reached by scrolling inside the input.
    expect(await overflows(page)).toBe(true)

    // Back under the limit: the input shrinks and the toggle goes away.
    await page.locator(input).fill('one line')
    expect(await height(page)).toBeCloseTo(natural, 0)
    await expect(page.locator(toggle)).toHaveCount(0)
  })

  test('the toggle lets the input grow to six lines, and sending folds it back', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })

    const natural = await height(page)
    const folded = Math.max(await cap(page, 3), natural)
    const open = await cap(page, 6)
    const area = page.locator('.inputarea')

    await page.locator(input).fill(lines(5))
    expect(await height(page)).toBeCloseTo(folded, 0)
    const before = await area.boundingBox()

    await page.locator(toggle).click()
    await expect(page.locator(toggle)).toHaveAttribute('aria-expanded', 'true')
    // Five lines fit in six: the input shows them all, growing upward from where it ended.
    await expect.poll(() => height(page)).toBeGreaterThan(folded)
    expect(await height(page)).toBeLessThan(open)
    expect(await overflows(page)).toBe(false)
    const after = await area.boundingBox()
    expect(after.y + after.height).toBeCloseTo(before.y + before.height, 0)
    expect(after.y).toBeLessThan(before.y)
    // The text keeps the focus.
    await expect(page.locator(input)).toBeFocused()

    // More than six lines: it stops at six and scrolls inside.
    await page.locator(input).fill(lines(12))
    expect(await height(page)).toBeCloseTo(open, 0)
    expect(await overflows(page)).toBe(true)

    // The toggle folds it back to three lines.
    await page.locator(toggle).click()
    await expect(page.locator(toggle)).toHaveAttribute('aria-expanded', 'false')
    expect(await height(page)).toBeCloseTo(folded, 0)

    // Sending folds it back too.
    await page.locator(toggle).click()
    await expect(page.locator(toggle)).toHaveAttribute('aria-expanded', 'true')
    await page.locator('[data-testid=chat-send-button]').click()
    await expect(page.locator(input)).toHaveValue('')
    await expect(page.locator(toggle)).toHaveCount(0)
    await page.locator(input).fill(lines(5))
    await expect(page.locator(toggle)).toHaveAttribute('aria-expanded', 'false')
    expect(await height(page)).toBeCloseTo(folded, 0)
  })
})
