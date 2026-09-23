// Regression: the chat stays pinned to the bottom while its content keeps growing.
//
// Until 2026-09-23 messages carried `content-visibility: auto`: off-screen messages
// counted as zero height and grew when they entered the viewport, so each jump to
// the bottom resized the content in between and opening a session or pressing ↓
// stopped short (7,000+ px on chromium). The "user left the bottom" decision now
// also ignores content growth (features/chat/stickToBottom.js).

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

test.describe('regression: stick to bottom', () => {
  test('a long history opens at the bottom, and ↓ goes all the way down', async ({ page, request }) => {
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
    expect(await distanceFromBottom(page)).toBeLessThanOrEqual(30)

    // Read older messages, then come back with ↓. Scroll without the CSS smooth
    // animation, the way a finger moves it (an assignment would animate upward and
    // keep moving after ↓ jumps down).
    await page.locator('.messages').evaluate((el) => { el.scrollTo({ top: el.scrollHeight / 3, behavior: 'instant' }) })
    await expect(page.locator('.scroll-btn')).toBeVisible()
    await page.locator('.scroll-btn').click()
    await page.waitForTimeout(1000)
    expect(await distanceFromBottom(page)).toBeLessThanOrEqual(30)
    await expect(page.locator('.scroll-btn')).toHaveCount(0)
  })
})
