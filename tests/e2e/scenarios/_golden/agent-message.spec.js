// Golden path: a message one tab's Claude sends another tab arrives there as
// its own bubble, labelled with the sender, and is told apart from what the
// operator typed.
//
// The e2e backend has no Claude process: POST /agent-messages appends the
// enveloped text to the receiver's JSONL as a user row, exactly as the
// operator's send path does in this mode, and the watcher delivers it.

import { test, expect } from '@playwright/test'
import { seedSession, appendEvent } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const BODY = 'The page builder drops the last row when a title wraps.\nSee page 3 of the sample deck.'
const BODY_HEAD = 'The page builder drops the last row when a title wraps.'
const BODY_REST = 'See page 3 of the sample deck.'

// 伝言の吹き出しは既定で畳まれている。 まだ畳まれていれば 1 行を押して開く。
async function unfold(relayed) {
  const toggle = relayed.locator('[data-testid=relayed-toggle]')
  if ((await toggle.getAttribute('aria-expanded')) !== 'true') await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
}

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
    await expect(operatorWords).toHaveCount(0)   // folded: the quote shows only once opened
    await unfold(asked)
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

  test('a message that arrives while Claude is working is shown, and so is what the operator typed meanwhile', async ({ page, request }, testInfo) => {
    const receiver = await seedSession(request, 'e2e-tab-b')
    await openClient(page, { sid: receiver.sid })

    // While Claude works, what enters the terminal is not recorded as a user row:
    // Claude queues it and, once it hands it over between two steps, records it as
    // an attachment row. The rows below have the shape of the real record (a relayed
    // message enters as a paste, so it is recorded inside the paste wrapper).
    const queued = (uuid, prompt) => ({
      type: 'attachment',
      uuid,
      isSidechain: false,
      timestamp: new Date().toISOString(),
      attachment: { type: 'queued_command', prompt, commandMode: 'prompt', origin: { kind: 'human' }, humanTurn: true },
    })
    const envelope = [
      'Message from a session on another machine, relayed by the client (the operator did not type this):',
      '<agent-message from="tab A @home" session="home:ses_far">',
      BODY,
      '</agent-message>',
    ].join('\n')
    appendEvent(receiver.jsonl_path, queued('e2e-queued-typed', 'and check the footer too'))
    appendEvent(receiver.jsonl_path, queued('e2e-queued-relayed', `<pasted_content id="4a58">\n${envelope}\n</pasted_content id="4a58">`))

    const relayed = page.locator('[data-testid=message-bubble-user].relayed')
    const typed = page.locator('[data-testid=message-bubble-user]:not(.relayed)').filter({ hasText: 'and check the footer too' })
    const bothShown = async () => {
      await expect(relayed).toHaveCount(1, { timeout: 20_000 })
      await expect(relayed.locator('[data-testid=relayed-from]')).toContainText('tab A @home')
      await expect(relayed).toContainText('The page builder drops the last row')
      await expect(relayed).not.toContainText('pasted_content')
      await expect(relayed).not.toContainText('relayed by the client')
      await expect(typed).toHaveCount(1)
    }
    await bothShown()
    await page.screenshot({ path: testInfo.outputPath('agent-message-while-working.png') })

    // Both come back from the record: a reload does not lose them, nor show them twice.
    await page.reload()
    await bothShown()
  })

  test('a message from another tab is folded to one line and opens on a tap', async ({ page, request }, testInfo) => {
    const sender = await seedSession(request, 'e2e-tab-a')
    const receiver = await seedSession(request, 'e2e-tab-b')
    await openClient(page, { sid: receiver.sid })

    // A message with a blank line before its text: the folded line shows the first filled line.
    const res = await request.post('/agent-messages', {
      form: { to: 'tab B', from: sender.sid, text: `\n${BODY}` },
    })
    expect(res.ok()).toBeTruthy()
    const relayed = page.locator('[data-testid=message-bubble-user].relayed')
    await expect(relayed).toHaveCount(1, { timeout: 20_000 })
    const toggle = relayed.locator('[data-testid=relayed-toggle]')

    // Folded by default: who sent it and the head of the text, nothing more.
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await expect(relayed.locator('[data-testid=relayed-from]')).toContainText('tab A')
    await expect(relayed.locator('[data-testid=relayed-head]')).toHaveText(BODY_HEAD)
    await expect(relayed).not.toContainText(BODY_REST)
    await expect(relayed.locator('[data-testid=relayed-operator]')).toHaveCount(0)
    await page.setViewportSize({ width: 390, height: 844 })
    await page.screenshot({ path: testInfo.outputPath('agent-message-folded.png') })

    // A tap opens it: the text in full. (The operator's quote opening is checked in the operator-said test.)
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await expect(relayed).toContainText(BODY_REST)
    await expect(relayed.locator('[data-testid=relayed-head]')).toHaveCount(0)
    await expect(relayed.locator('[data-testid=relayed-from]')).toContainText('tab A')
    await page.screenshot({ path: testInfo.outputPath('agent-message-unfolded.png') })

    // A second tap folds it again.
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await expect(relayed).not.toContainText(BODY_REST)
  })

  test('a ticket handed to the tab stays one line and is not folded', async ({ page, request }) => {
    const receiver = await seedSession(request, 'e2e-tab-b')
    await openClient(page, { sid: receiver.sid })

    // The line the backend writes when it hands a ticket on: the envelope carries ticket="<id>".
    const envelope = [
      'Message from another session, relayed by the client (the operator did not type this):',
      '<agent-message from="tab A" session="ses_far" ticket="tk-fold-1">',
      'ticket tk-fold-1 is yours now',
      '</agent-message>',
    ].join('\n')
    appendEvent(receiver.jsonl_path, {
      type: 'attachment',
      uuid: 'e2e-queued-ticket',
      isSidechain: false,
      timestamp: new Date().toISOString(),
      attachment: { type: 'queued_command', prompt: envelope, commandMode: 'prompt', origin: { kind: 'human' }, humanTurn: true },
    })
    const relayed = page.locator('[data-testid=message-bubble-user].relayed')
    await expect(relayed).toHaveCount(1, { timeout: 20_000 })
    await expect(relayed.locator('[data-testid=relayed-ticket-link]')).toContainText('tk-fold-1')
    await expect(relayed.locator('[data-testid=relayed-toggle]')).toHaveCount(0)
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
