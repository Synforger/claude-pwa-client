// Golden path: the two messages of an automatic session rollover arrive as
// their own bubbles, told apart from what the operator typed and from a
// message relayed from another tab.
//
// The backend types both messages the way the operator's send path does, so
// in this mode they are appended to the tab's JSONL as user rows and the
// watcher delivers them. Whether and when the backend asks, and what the
// restart does, is covered by the backend tests: there is no Claude process
// here to close or to start again.

import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const OPENING = 'Automatic session rollover, sent by the client (the operator did not type this):'
const closeMessage = (sid, reason, pct, minutes, why) =>
  `${OPENING}\n<session-rollover phase="close" reason="${reason}" context_pct="${pct}" idle_minutes="${minutes}">\n`
  + `${why} Wrap up at the next stopping point and hand over: write down what the next session needs, `
  + `then ask the client to start it (POST /sessions/${sid}/rollover, form field \`text\` = what the next session opens with).\n`
  + '</session-rollover>'
const startMessage = (text) => `${OPENING}\n<session-rollover phase="start">\n${text}\n</session-rollover>`

test.describe('golden: session-rollover', () => {
  test('a request to close and the first message of the new session show as rollover bubbles', async ({ page, request }, testInfo) => {
    const sender = await seedSession(request, 'e2e-tab-a')
    const tab = await seedSession(request, 'e2e-tab-b')
    await openClient(page, { sid: tab.sid })
    const send = (text) => request.post(`/pty/${tab.sid}/send`, { data: { text, enter: true } })

    // What the operator types is an ordinary bubble.
    await page.locator('[data-testid=chat-input]').fill('build the sample deck and fix what breaks')
    await page.locator('[data-testid=chat-send-button]').click()
    const typed = page.locator('[data-testid=message-bubble-user]:not(.relayed)')
    await expect(typed.filter({ hasText: 'build the sample deck' })).toHaveCount(1, { timeout: 20_000 })

    // A message from another tab, for comparison.
    const relayed = await request.post('/agent-messages', {
      form: { to: tab.sid, from: sender.sid, text: 'The page builder drops the last row when a title wraps.' },
    })
    expect(relayed.ok()).toBeTruthy()
    await expect(page.locator('[data-testid=relayed-from]')).toHaveCount(1, { timeout: 20_000 })

    // The backend asks the session to close: once while it works, once after it sat quiet.
    expect((await send(closeMessage(tab.sid, 'context', 62, 0, 'Context is at 62%.'))).ok()).toBeTruthy()
    const labels = page.locator('[data-testid=rollover-label]')
    const bodies = page.locator('[data-testid=rollover-body]')
    await expect(labels).toHaveCount(1, { timeout: 20_000 })
    await expect(bodies.nth(0)).toContainText('62')
    expect((await send(closeMessage(tab.sid, 'idle', 45, 51,
      'Context is at 45% and this session has been quiet for 51 minutes.'))).ok()).toBeTruthy()
    await expect(labels).toHaveCount(2, { timeout: 20_000 })
    await expect(bodies.nth(1)).toContainText('45')
    await expect(bodies.nth(1)).toContainText('51')

    // The session started in its place opens with what the old one handed over.
    expect((await send(startMessage('tier=normal\nmode=continue'))).ok()).toBeTruthy()
    await expect(labels).toHaveCount(3, { timeout: 20_000 })
    await expect(bodies.nth(2)).toContainText('mode=continue')

    // None of them shows its envelope, and none is taken for the operator's own.
    const rollover = page.locator('[data-testid=message-bubble-user].relayed').filter({ has: labels })
    await expect(rollover).toHaveCount(3)
    for (const hidden of ['session-rollover', 'sent by the client', 'POST /sessions']) {
      await expect(page.locator('[data-testid=message-bubble-user]').filter({ hasText: hidden })).toHaveCount(0)
    }
    await expect(typed).toHaveCount(1)

    await page.screenshot({ path: testInfo.outputPath('session-rollover.png') })
    // The same view at a phone's width, whatever the project's own viewport is.
    await page.setViewportSize({ width: 390, height: 844 })
    await expect(labels.nth(2)).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('session-rollover-narrow.png') })
  })
})
