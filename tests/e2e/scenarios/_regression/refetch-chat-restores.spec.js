// Regression: "Reload chat" (⋯ menu) emptied the chat and nothing came back.
//
// It emptied the screen first and then waited for the server to send the
// conversation again. When the server had nothing to send for that tab (after a
// backend restart it could not find the tab's record until the next message),
// the screen stayed empty, and the copy kept in the browser was gone too.
// A reload now asks the server first and rebuilds the chat only from an answer.

import { test, expect } from '@playwright/test'
import { renameSync } from 'node:fs'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2erefetch'

function conversation() {
  const at = (n) => new Date(Date.UTC(2026, 0, 1, 0, 0, n)).toISOString()
  return [
    { type: 'user', uuid: 'u-refetch-1', message: { role: 'user', content: 'first question' }, timestamp: at(1) },
    { type: 'assistant', uuid: 'a-refetch-1',
      message: { id: 'msg_refetch_1', role: 'assistant', model: 'claude-opus-4-7', stop_reason: 'end_turn',
        content: [{ type: 'text', text: 'first answer' }] },
      timestamp: at(2) },
    { type: 'user', uuid: 'u-refetch-2', message: { role: 'user', content: 'second question' }, timestamp: at(3) },
    { type: 'assistant', uuid: 'a-refetch-2',
      message: { id: 'msg_refetch_2', role: 'assistant', model: 'claude-opus-4-7', stop_reason: 'end_turn',
        content: [{ type: 'text', text: 'second answer' }] },
      timestamp: at(4) },
  ]
}

async function seed(request, sid) {
  const res = await request.post('/debug/e2e/seed', {
    data: { sid, agent_id: 'agent_e2e', account_id: 'e2e', title: 'reload chat', jsonl_events: conversation() },
  })
  expect(res.ok()).toBeTruthy()
  return res.json()
}

async function reloadChat(page) {
  await page.locator('[data-testid=more-menu-toggle]').click()
  await page.locator('[data-testid=refetch-chat]').click()
}

async function expectConversation(page) {
  const users = page.locator('[data-testid=message-bubble-user]')
  await expect(users).toHaveCount(2, { timeout: 15_000 })
  await expect(users.first()).toContainText('first question')
  await expect(users.last()).toContainText('second question')
  await expect(page.getByText('first answer')).toBeVisible()
  await expect(page.getByText('second answer')).toBeVisible()
}

test.describe('regression: reload chat restores the conversation', () => {
  test('the messages are back on screen after a reload', async ({ page, request }) => {
    await seed(request, SID)
    const dialogs = []
    page.on('dialog', (d) => { dialogs.push(d.message()); d.accept() })
    await openClient(page, { sid: SID })
    await expectConversation(page)

    await reloadChat(page)
    await expectConversation(page)
    expect(dialogs).toEqual([])
  })

  test('a reload leaves the chat as it is while the server cannot read the record', async ({ page, request }) => {
    const sid = `${SID}away`
    const seeded = await seed(request, sid)
    const dialogs = []
    page.on('dialog', (d) => { dialogs.push(d.message()); d.accept() })
    await openClient(page, { sid })
    await expectConversation(page)

    // The server loses sight of the record (here: the file is moved away).
    const away = `${seeded.jsonl_path}.away`
    renameSync(seeded.jsonl_path, away)
    try {
      await reloadChat(page)
      // It says so, once, instead of emptying the screen ...
      await expect.poll(() => dialogs.length).toBe(1)
      // ... and what was on screen is still there after the stream has reconnected.
      await page.waitForTimeout(3000)
      await expectConversation(page)
    } finally {
      renameSync(away, seeded.jsonl_path)
    }

    // The copy kept in the browser survived too: a page reload still shows the conversation.
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible' })
    await expectConversation(page)

    // Once the server can read the record again, a reload rebuilds the chat without complaint.
    await reloadChat(page)
    await expectConversation(page)
    expect(dialogs).toHaveLength(1)
  })
})
