// Regression: what the user reads above the bottom stays where it is while new messages keep coming.
//
// While the user is above the bottom the chat window is frozen, so that the messages on screen do not shift. A
// conversation is held at MAX_MESSAGES (200): once it is full, each new message drops the oldest off the top. The window
// used to be remembered by its number in the list, so the same number pointed at the next message with every new one:
// the first message of the window left the DOM each time and what was being read moved up. The window is now remembered
// by the message it starts at. The scenario fills a conversation, scrolls up to read, streams fewer new messages than the
// window holds (so the first one is not dropped), and expects the bubble in the middle of the screen to stay where it was.

import { test, expect } from '@playwright/test'
import { appendEvent } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'
import { DISPLAY_LIMIT } from '../../../../frontend/src/_common/displayLimit.js'

const SID = 'ses_e2ereading'
const HISTORY_MESSAGES = 230          // more than the 200 a conversation keeps: the list is full when it opens
const NEW_MESSAGES = 90               // fewer than DISPLAY_LIMIT: the message the window froze on is still in the list
const NEW_MESSAGE_INTERVAL_MS = 120
const LINES_PER_MESSAGE = 8
const POSITION_TOLERANCE_PX = 3

const messageRow = (index, stamp) => ({
  type: 'assistant', uuid: `a-reading-${index}`,
  message: {
    id: `msg_reading_${index}`, role: 'assistant', model: 'claude-opus-4-7', stop_reason: 'end_turn',
    content: [{ type: 'text', text: Array.from({ length: LINES_PER_MESSAGE }, (_, i) => `message ${index} line ${i}`).join('\n\n') }],
  },
  timestamp: new Date(stamp).toISOString(),
})

// Reads up four steps of 500 px, the way each screen does it. A computer turns the mouse wheel. A phone has no wheel
// (mobile WebKit refuses one), so a finger touches the list first and then the list moves: the touch is what tells the
// screen the person took over from the pull to the bottom.
async function readUp(page, isMobile) {
  if (!isMobile) await page.locator('.messages').hover()
  for (let i = 0; i < 4; i++) {
    if (isMobile) {
      await page.evaluate(() => {
        const list = document.querySelector('.messages')
        list.dispatchEvent(new TouchEvent('touchstart', { bubbles: true }))
        list.scrollBy(0, -500)
      })
    } else {
      await page.mouse.wheel(0, -500)
    }
    await page.waitForTimeout(150)
  }
}

test.describe('regression: reading position holds', () => {
  test.setTimeout(120_000)

  test('a bubble read above the bottom stays put while new messages come to a full conversation', async ({ page, request, isMobile }) => {
    const start = Date.now() - 3_600_000
    const seeded = await request.post('/debug/e2e/seed', {
      data: {
        sid: SID, agent_id: 'agent_e2e', account_id: 'e2e', title: 'reading',
        jsonl_events: Array.from({ length: HISTORY_MESSAGES }, (_, i) => messageRow(i, start + i * 1000)),
      },
    })
    expect(seeded.ok()).toBeTruthy()
    const { jsonl_path: jsonlPath } = await seeded.json()
    await openClient(page, { sid: SID })

    // The bubble across the middle of the list, and where it is on screen. When the middle falls in the gap between two
    // bubbles, the one just below it.
    const reading = () => page.evaluate(() => {
      const list = document.querySelector('.messages')
      const box = list.getBoundingClientRect()
      const middle = box.top + box.height / 2
      for (const bubble of list.children) {
        const rect = bubble.getBoundingClientRect()
        if (rect.bottom > middle) {
          return { uuid: bubble.getAttribute('data-cpc-uuid'), offset: Math.round(rect.top - box.top), bubbles: list.children.length, arrowShown: !!document.querySelector('.scroll-btn') }
        }
      }
      return { uuid: null, offset: null, bubbles: list.children.length, arrowShown: !!document.querySelector('.scroll-btn') }
    })
    const positionOf = (uuid) => page.evaluate((id) => {
      const list = document.querySelector('.messages')
      const bubble = [...list.children].find(b => b.getAttribute('data-cpc-uuid') === id)
      return bubble ? Math.round(bubble.getBoundingClientRect().top - list.getBoundingClientRect().top) : null
    }, uuid)

    // Scroll up to read: the ↓ button shows and the window freezes.
    await readUp(page, isMobile)
    await expect(page.locator('.scroll-btn')).toBeVisible({ timeout: 5_000 })
    await page.waitForTimeout(1000)                      // the scroll is animated
    const before = await reading()
    expect(before.uuid).not.toBeNull()
    expect(before.bubbles).toBeLessThanOrEqual(DISPLAY_LIMIT + 1)

    // New messages keep coming while the user reads.
    for (let i = 0; i < NEW_MESSAGES; i++) {
      appendEvent(jsonlPath, messageRow(HISTORY_MESSAGES + i, Date.now()))
      await page.waitForTimeout(NEW_MESSAGE_INTERVAL_MS)
    }
    await page.waitForTimeout(1500)

    const after = await reading()
    const sameBubbleNow = await positionOf(before.uuid)
    expect(after.arrowShown).toBe(true)                  // still reading above the bottom
    expect(after.bubbles).toBeGreaterThan(before.bubbles)   // the window grew toward the newest
    expect(after.bubbles).toBeLessThanOrEqual(200 + 1)   // and is held by the conversation's limit
    expect(sameBubbleNow).not.toBeNull()
    expect(Math.abs(sameBubbleNow - before.offset)).toBeLessThanOrEqual(POSITION_TOLERANCE_PX)
  })
})
