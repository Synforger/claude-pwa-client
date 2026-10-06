// Regression: the chat stays pinned to the bottom while its content keeps growing.
//
// Until 2026-09-23 messages carried `content-visibility: auto`: off-screen messages
// counted as zero height and grew when they entered the viewport, so each jump to
// the bottom resized the content in between and opening a session or pressing ↓
// stopped short (7,000+ px on chromium). The "user left the bottom" decision now
// also ignores content growth (features/chat/stickToBottom.js).
//
// Until 2026-10-06 ↓ also lost to a scroll that was still in motion when it was
// pressed: the upward movement left over from a flick (or from an animated scroll
// in flight) read as "the user scrolled up", the pin came off, and the list stopped
// 189-264 px short with ↓ showing again.

import { test, expect } from '@playwright/test'
import { seedSession, appendEvent } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'

function longReply(i) {
  const code = Array.from({ length: 12 }, (_, k) => `const v${k} = ${i} * ${k}  // line ${k}`).join('\n')
  return `Reply ${i}\n\n\`\`\`js\n${code}\n\`\`\`\n\n| a | b |\n|---|---|\n| ${i} | ${i + 1} |`
}

async function distanceFromBottom(page) {
  return page.locator('.messages').evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight)
}

async function openLongHistory(page, request) {
  const seeded = await seedSession(request, 'e2e-chat-golden')
  const base = Date.now() - 60_000
  for (let i = 0; i < 40; i++) {
    appendEvent(seeded.jsonl_path, {
      type: 'assistant',
      uuid: `a-stick-${i}`,
      message: {
        id: `msg_stick_${i}`,
        role: 'assistant',
        content: [{ type: 'text', text: longReply(i) }],
        stop_reason: 'end_turn',
        model: 'claude-opus-4-7',
      },
      timestamp: new Date(base + i * 1000).toISOString(),
    })
  }

  await openClient(page, { sid: SID })
  await expect(page.locator('[data-testid=message-bubble-agent]').last()).toContainText('Reply 39', { timeout: 15_000 })
  await page.waitForTimeout(1500)
}

// Scroll without the CSS smooth animation, the way a finger moves the list (an
// assignment to scrollTop would animate and keep moving afterwards).
async function scrollUpTo(page, fraction) {
  await page.locator('.messages').evaluate((el, f) => { el.scrollTo({ top: el.scrollHeight * f, behavior: 'instant' }) }, fraction)
}

async function expectAtBottom(page) {
  await page.waitForTimeout(1000)
  expect(await distanceFromBottom(page)).toBeLessThanOrEqual(30)
  await expect(page.locator('.scroll-btn')).toHaveCount(0)
}

test.describe('regression: stick to bottom', () => {
  test('a long history opens at the bottom, and ↓ goes all the way down', async ({ page, request }) => {
    await openLongHistory(page, request)
    expect(await distanceFromBottom(page)).toBeLessThanOrEqual(30)

    // Read older messages, then come back with ↓.
    await scrollUpTo(page, 1 / 3)
    await expect(page.locator('.scroll-btn')).toBeVisible()
    await page.locator('.scroll-btn').click()
    await expectAtBottom(page)
  })

  test('↓ pressed while a flick still carries the list upward reaches the bottom', async ({ page, request }) => {
    await openLongHistory(page, request)
    await scrollUpTo(page, 0.6)
    await expect(page.locator('.scroll-btn')).toBeVisible()

    // A flick's momentum: the list keeps moving up, frame by frame and slowing
    // down, with no finger on it and no input event.
    await page.locator('.messages').evaluate((el) => {
      let n = 0
      const step = () => {
        el.scrollBy({ top: -60 + n * 3, behavior: 'instant' })
        if (++n < 18) requestAnimationFrame(step)
      }
      requestAnimationFrame(step)
    })
    await page.waitForTimeout(60)
    await page.locator('.scroll-btn').click()
    await expectAtBottom(page)

    // Once the list has come to rest, scrolling up is the user's again.
    await scrollUpTo(page, 1 / 3)
    await expect(page.locator('.scroll-btn')).toBeVisible()
  })

  test('↓ pressed while an animated scroll upward is in flight reaches the bottom', async ({ page, request }) => {
    await openLongHistory(page, request)

    // An assignment animates (`.messages` has scroll-behavior: smooth) and is
    // still moving when ↓ is pressed.
    await page.locator('.messages').evaluate((el) => { el.scrollTop = el.scrollHeight / 4 })
    await expect(page.locator('.scroll-btn')).toBeVisible()
    await page.waitForTimeout(120)
    await page.locator('.scroll-btn').click()
    await expectAtBottom(page)
  })
})
