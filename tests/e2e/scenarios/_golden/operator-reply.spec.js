// Golden path: the last answer given to the operator stays in a drawer at the top right (the bookmark), however far
// the chat has moved on. A note from another tab and the reply to it come after the answer; the drawer still shows the
// answer, with the head line of the question and the time, and does not cover the left side of the chat.
//
// The e2e backend has no Claude process: the operator's send path writes the user row, and the scenario writes what
// Claude writes (an assistant row) to the tab's JSONL, so the watcher delivers it.

import { test, expect } from '@playwright/test'
import { seedSession, appendEvent } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const QUESTION = 'What should we do about page 3?'
const ANSWER_HEAD = 'My recommendation: keep the title on one line.'
const ANSWER = `${ANSWER_HEAD}\n\n- shrink the title font to 28pt\n- keep the sample deck's grid`
const NOTE = 'The page builder drops the last row when a title wraps.'

function assistantRow(id, text) {
  return {
    type: 'assistant', uuid: `a-reply-${id}`, timestamp: new Date().toISOString(),
    message: { id: `msg_reply_${id}`, role: 'assistant', content: [{ type: 'text', text }], stop_reason: 'end_turn', model: 'claude-opus-4-7' },
  }
}

test.describe('golden: operator-reply', () => {
  test('the drawer keeps the answer while a note and its reply flow past in the chat', async ({ page, request }, testInfo) => {
    const tab = await seedSession(request, 'e2e-tab-b')
    const sender = await seedSession(request, 'e2e-tab-a')
    await openClient(page, { sid: tab.sid })
    await expect(page.locator('[data-testid=operator-reply-knob]')).toHaveCount(0)   // nothing answered yet

    await page.locator('[data-testid=chat-input]').fill(QUESTION)
    await page.locator('[data-testid=chat-send-button]').click()
    await expect(page.locator('[data-testid=message-bubble-user]').filter({ hasText: QUESTION })).toHaveCount(1, { timeout: 20_000 })
    appendEvent(tab.jsonl_path, assistantRow('answer', ANSWER))
    await expect(page.getByText(ANSWER_HEAD).first()).toBeVisible({ timeout: 20_000 })

    // A note from another tab arrives, and the tab answers the note: the chat moves on.
    const relayed = await request.post('/agent-messages', { form: { to: tab.sid, from: sender.sid, text: NOTE } })
    expect(relayed.ok()).toBeTruthy()
    await expect(page.locator('[data-testid=message-bubble-user].relayed')).toHaveCount(1, { timeout: 20_000 })
    appendEvent(tab.jsonl_path, assistantRow('to-note', 'Noted, I will look at the page builder.'))
    await expect(page.getByText('Noted, I will look at the page builder.')).toBeVisible({ timeout: 20_000 })

    // The knob carries a dot (the answer was not opened yet); the drawer opens to the answer, not to the reply to the note.
    const knob = page.locator('[data-testid=operator-reply-knob]')
    await expect(knob).toBeVisible()
    await expect(page.locator('[data-testid=operator-reply-dot]')).toHaveCount(1)
    await page.screenshot({ path: testInfo.outputPath('operator-reply-knob.png') })
    await knob.click()
    const panel = page.locator('[data-testid=operator-reply-panel]')
    await expect(panel).toContainText(ANSWER_HEAD)
    await expect(panel).toContainText('shrink the title font to 28pt')
    await expect(panel).not.toContainText('Noted, I will look')
    await expect(page.locator('[data-testid=operator-reply-prompt]')).toHaveText(QUESTION)
    await expect(page.locator('[data-testid=operator-reply-dot]')).toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath('operator-reply-open.png') })

    // The drawer leans on the right and leaves the left side of the chat uncovered.
    const viewport = page.viewportSize()
    const box = await panel.boundingBox()
    expect(box.x + box.width).toBeGreaterThan(viewport.width - 2)
    expect(box.width).toBeLessThanOrEqual(640)
    expect(box.height).toBeLessThanOrEqual(viewport.height * 0.5 + 1)

    // The same view at a phone's width, whatever the project's own viewport is.
    await page.setViewportSize({ width: 390, height: 844 })
    await expect(panel).toBeVisible()
    const narrow = await panel.boundingBox()
    expect(narrow.width).toBeGreaterThanOrEqual(279)
    await page.screenshot({ path: testInfo.outputPath('operator-reply-open-narrow.png') })

    // The knob closes it, and so does a press outside.
    await knob.click()
    await expect(panel).toHaveCount(0)
    await knob.click()
    await expect(panel).toBeVisible()
    await page.locator('[data-testid=chat-input]').click()
    await expect(panel).toHaveCount(0)
  })
})
