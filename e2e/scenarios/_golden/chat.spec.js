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

// The input grows with what is typed, stops at six lines, and past that offers
// a toggle that opens it over the visible chat area.
test.describe('golden: chat input size', () => {
  const input = '[data-testid=chat-input]'
  const toggle = '[data-testid=chat-input-size-toggle]'
  const lines = (n) => Array.from({ length: n }, (_, i) => `line ${i + 1}`).join('\n')
  const height = (page) => page.locator(input).evaluate((el) => el.getBoundingClientRect().height)
  // The collapsed limit, read from the page's own styles (= six lines + padding + border).
  const cap = (page) => page.locator(input).evaluate((el) => {
    const cs = getComputedStyle(el)
    const px = (v) => parseFloat(v) || 0
    return px(cs.lineHeight) * 6 + px(cs.paddingTop) + px(cs.paddingBottom)
      + px(cs.borderTopWidth) + px(cs.borderBottomWidth)
  })

  test('grows with the text and stops at six lines', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })

    const natural = await height(page)
    const limit = await cap(page)
    expect(limit).toBeGreaterThan(natural)

    await page.locator(input).fill('one line')
    expect(await height(page)).toBeCloseTo(natural, 0)
    await expect(page.locator(toggle)).toHaveCount(0)

    await page.locator(input).fill(lines(5))
    const five = await height(page)
    expect(five).toBeGreaterThan(natural)
    expect(five).toBeLessThan(limit)

    await page.locator(input).fill(lines(6))
    expect(await height(page)).toBeCloseTo(limit, 0)
    await expect(page.locator(toggle)).toHaveCount(0)

    await page.locator(input).fill(lines(7))
    expect(await height(page)).toBeCloseTo(limit, 0)
    await expect(page.locator(toggle)).toBeVisible()
    await expect(page.locator(toggle)).toHaveAttribute('aria-expanded', 'false')
    // The seventh line is there, reached by scrolling inside the input.
    expect(await page.locator(input).evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true)

    // Back under the limit: the input shrinks and the toggle goes away.
    await page.locator(input).fill('one line')
    expect(await height(page)).toBeCloseTo(natural, 0)
    await expect(page.locator(toggle)).toHaveCount(0)
  })

  test('the toggle opens the input over the chat area, and sending folds it back', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })

    await page.locator(input).fill(lines(12))
    const limit = await cap(page)
    const reserved = () => page.evaluate(
      () => getComputedStyle(document.documentElement).getPropertyValue('--chat-input-h').trim(),
    )
    const before = await reserved()
    const area = page.locator('.inputarea')
    const collapsed = await area.boundingBox()
    const listTop = await page.locator('.cpc-chat-panel > :first-child').evaluate(
      (el) => el.getBoundingClientRect().top,
    )

    await page.locator(toggle).click()
    await expect(area).toHaveClass(/expanded/)
    await expect(page.locator(toggle)).toHaveAttribute('aria-expanded', 'true')
    const open = await area.boundingBox()
    // From the top of the message list down to where the input already ended, in the same column.
    expect(open.y).toBeCloseTo(listTop, 0)
    expect(open.y + open.height).toBeCloseTo(collapsed.y + collapsed.height, 0)
    expect(open.x).toBeCloseTo(collapsed.x, 0)
    expect(open.width).toBeCloseTo(collapsed.width, 0)
    expect(await height(page)).toBeGreaterThan(limit)
    // The text keeps the focus, and what the overlays reserve below them does not move.
    await expect(page.locator(input)).toBeFocused()
    expect(await reserved()).toBe(before)

    // An overlay opened afterwards is on top of the expanded input.
    await page.locator('[data-testid=favorites-open-button]').click()
    await expect(page.locator('.tree-overlay')).toBeVisible()
    const onTop = await page.evaluate(() => {
      const el = document.elementFromPoint(window.innerWidth / 2, window.innerHeight / 2)
      return !!el && !!el.closest('.tree-overlay')
    })
    expect(onTop).toBe(true)
    await page.locator('.tree-overlay .modal-close').click()

    await page.locator(toggle).click()
    await expect(area).not.toHaveClass(/expanded/)
    expect(await height(page)).toBeCloseTo(limit, 0)

    await page.locator(toggle).click()
    await expect(area).toHaveClass(/expanded/)
    await page.locator('[data-testid=chat-send-button]').click()
    await expect(area).not.toHaveClass(/expanded/)
    await expect(page.locator(input)).toHaveValue('')
    await expect(page.locator(toggle)).toHaveCount(0)
  })
})
