// Golden path: a message one tab's Claude sends another tab arrives there as
// its own bubble, labelled with the sender, and is told apart from what the
// operator typed.
//
// The e2e backend has no Claude process: POST /agent-messages appends the
// enveloped text to the receiver's JSONL as a user row, exactly as the
// operator's send path does in this mode, and the watcher delivers it.

import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const BODY = 'The page builder drops the last row when a title wraps.\nSee page 3 of the sample deck.'

test.describe('golden: agent-message', () => {
  test('a message from another tab shows who sent it, apart from the operator\'s own', async ({ page, request }, testInfo) => {
    const sender = await seedSession(request, 'e2e-tab-a')
    const receiver = await seedSession(request, 'e2e-tab-b')
    await openClient(page, { sid: receiver.sid })

    const res = await request.post('/agent-messages', {
      form: { to: 'tab B', from: sender.sid, text: BODY },
    })
    expect(res.ok()).toBeTruthy()
    expect((await res.json()).to).toBe(receiver.sid)

    const relayed = page.locator('[data-testid=message-bubble-user].relayed')
    await expect(relayed).toHaveCount(1, { timeout: 20_000 })
    await expect(relayed.locator('[data-testid=relayed-from]')).toContainText('tab A')
    await expect(relayed).toContainText('The page builder drops the last row')
    await expect(relayed).not.toContainText('agent-message')
    await expect(relayed).not.toContainText('relayed by the client')

    // What the operator types next is an ordinary bubble.
    await page.locator('[data-testid=chat-input]').fill('thanks, I will look at page 3')
    await page.locator('[data-testid=chat-send-button]').click()
    const typed = page.locator('[data-testid=message-bubble-user]:not(.relayed)')
    await expect(typed.filter({ hasText: 'thanks, I will look at page 3' })).toHaveCount(1, { timeout: 20_000 })
    await expect(page.locator('[data-testid=relayed-from]')).toHaveCount(1)

    await page.screenshot({ path: testInfo.outputPath('agent-message.png') })
    // The same view at a phone's width, whatever the project's own viewport is.
    await page.setViewportSize({ width: 390, height: 844 })
    await expect(relayed).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('agent-message-narrow.png') })
  })

  test('what the operator typed in the sender\'s tab travels with the message only when the sender asks', async ({ page, request }, testInfo) => {
    const sender = await seedSession(request, 'e2e-tab-a')
    const receiver = await seedSession(request, 'e2e-tab-b')
    await openClient(page, { sid: receiver.sid })

    // The operator types in tab A; then tab A's Claude writes to tab B.
    const said = await request.post(`/pty/${sender.sid}/send`, {
      data: { text: 'have the owner of the tool fix the wrapped title', enter: true },
    })
    expect(said.ok()).toBeTruthy()
    const relayed = page.locator('[data-testid=message-bubble-user].relayed')
    const operatorWords = page.locator('[data-testid=relayed-operator]')

    // Sent as it is, a message carries its body and nothing of what the operator typed.
    const plain = await request.post('/agent-messages', {
      form: { to: receiver.sid, from: sender.sid, text: 'The sample deck builds again.' },
    })
    expect((await plain.json()).operator_said).toBe(false)
    await expect(relayed).toHaveCount(1, { timeout: 20_000 })
    await expect(relayed).toContainText('The sample deck builds again.')
    await expect(operatorWords).toHaveCount(0)

    // When the sender asks for it, what the operator typed goes along.
    const res = await request.post('/agent-messages', {
      form: { to: receiver.sid, from: sender.sid, text: BODY, operator_said: 'true' },
    })
    expect((await res.json()).operator_said).toBe(true)
    await expect(relayed).toHaveCount(2, { timeout: 20_000 })
    const asked = relayed.filter({ hasText: 'The page builder drops the last row' })
    await expect(asked.locator('[data-testid=relayed-operator]')).toContainText('have the owner of the tool fix the wrapped title')
    await expect(asked).not.toContainText('operator-said')
    await expect(operatorWords).toHaveCount(1)

    // A message tab B's Claude sends back was started by a relayed message: even when
    // asked for, there are no operator's words to carry.
    const back = await request.post('/agent-messages', {
      form: { to: sender.sid, from: receiver.sid, text: 'fixed in the next build', operator_said: 'true' },
    })
    expect((await back.json()).operator_said).toBe(false)

    await page.setViewportSize({ width: 390, height: 844 })
    await expect(asked).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('agent-message-operator-said.png') })
  })

  test('a title no tab carries is refused, and nothing arrives', async ({ page, request }) => {
    const sender = await seedSession(request, 'e2e-tab-a')
    const receiver = await seedSession(request, 'e2e-tab-b')
    await openClient(page, { sid: receiver.sid })
    const before = await page.locator('[data-testid=message-bubble-user]').count()

    const res = await request.post('/agent-messages', {
      form: { to: 'no such tab', from: sender.sid, text: BODY },
    })
    expect(res.status()).toBe(404)
    expect((await res.json()).detail.code).toBe('agent_message_unknown_receiver')
    await page.waitForTimeout(1500)
    await expect(page.locator('[data-testid=message-bubble-user]')).toHaveCount(before)
  })
})
