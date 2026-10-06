// Regression: a message sent while Claude is working stays on screen, once.
//
// Claude queues what is typed mid-task. It writes no user row for it: only a
// queue-operation row when it is typed and, once it takes the message between
// two steps, an attachment row (`queued_command`) that carries the time the
// message was typed and is written after rows that are later in time. Any
// number of Claude's own steps can pass in between, and a phone can put the
// app away and bring it back meanwhile.
//
// The e2e backend plays Claude: marked as working (`setWorking`), it answers a
// send the way Claude does mid-task, and `queuedHandOver` writes the rows of
// Claude taking the message. The rows follow a real record.

import { test, expect } from '@playwright/test'
import { seedSession, appendEvent, setWorking, queuedHandOver, forgetSends } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'
const iso = (ms) => new Date(ms).toISOString()

// One step of Claude's own: a tool call and its result.
function step(jsonlPath, id, at, text) {
  appendEvent(jsonlPath, {
    type: 'assistant', uuid: `a-${id}`, timestamp: iso(at),
    message: { id: `msg_${id}`, role: 'assistant', stop_reason: 'tool_use',
      content: [...(text ? [{ type: 'text', text }] : []), { type: 'tool_use', id: `tool_${id}`, name: 'Bash', input: { command: 'ls' } }] },
  })
  appendEvent(jsonlPath, {
    type: 'user', uuid: `r-${id}`, timestamp: iso(at + 50),
    message: { role: 'user', content: [{ type: 'tool_result', tool_use_id: `tool_${id}`, content: 'ok' }] },
  })
}

async function start(page, request) {
  const seeded = await seedSession(request, 'e2e-chat-golden')
  await setWorking(request, SID, false)
  await openClient(page, { sid: SID })
  await page.evaluate(() => {
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const k = localStorage.key(i)
      if (k && k.startsWith('cpc.messages.')) localStorage.removeItem(k)
    }
  })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible' })
  await page.waitForTimeout(1500)

  // The first message starts a turn, and Claude begins working.
  const bubbles = page.locator('[data-testid=message-bubble-user]')
  await page.locator('[data-testid=chat-input]').fill('first message')
  await page.locator('[data-testid=chat-send-button]').click()
  await expect(bubbles.filter({ hasText: 'first message' })).toHaveAttribute('data-cpc-optimistic', '0', { timeout: 15_000 })
  const rid = Math.floor(performance.now() % 1e6).toString(16)
  step(seeded.jsonl_path, `first-${rid}`, Date.now(), 'looking at the first one')
  await expect(page.locator('[data-testid=message-bubble-agent]').filter({ hasText: 'looking at the first one' })).toHaveCount(1, { timeout: 10_000 })
  await setWorking(request, SID, true)
  return { seeded, rid, bubbles, second: bubbles.filter({ hasText: 'second message' }) }
}

// Send the second message while Claude works; resolves to the time Claude recorded it as typed.
async function sendSecond(page) {
  const answered = page.waitForResponse((res) => res.url().includes('/pty/') && res.url().endsWith('/send'))
  await page.locator('[data-testid=chat-input]').fill('second message')
  await page.locator('[data-testid=chat-send-button]').click()
  const body = await (await answered).json()
  expect(body.queued, 'the e2e backend queued the send, as Claude does mid-task').toBe(true)
  return body.typed_at
}

test.describe('regression: a message sent while Claude works', () => {
  test.afterEach(async ({ request }) => { await setWorking(request, SID, false) })

  test('stays on screen, once, until and after Claude takes it', async ({ page, request }) => {
    const { seeded, rid, bubbles, second } = await start(page, request)
    const typedAt = await sendSecond(page)
    await expect(second).toHaveCount(1)

    // Claude goes on with its own steps; the message waits.
    step(seeded.jsonl_path, `mid-${rid}`, Date.parse(typedAt) + 2000, 'still on the first one')
    await expect(page.locator('[data-testid=message-bubble-agent]').filter({ hasText: 'still on the first one' })).toHaveCount(1, { timeout: 10_000 })
    await expect(second, 'while it waits in the queue').toHaveCount(1)

    // Claude takes it, answers, and the turn ends.
    queuedHandOver(seeded.jsonl_path, { uuid: `q-${rid}`, text: 'second message', typedAt })
    await expect(second, 'once Claude has taken it').toHaveAttribute('data-cpc-uuid', `q-${rid}`, { timeout: 10_000 })
    appendEvent(seeded.jsonl_path, {
      type: 'assistant', uuid: `end-${rid}`, timestamp: iso(Date.parse(typedAt) + 8000),
      message: { id: `msg_end_${rid}`, role: 'assistant', stop_reason: 'end_turn', model: 'claude-opus-4-7',
        content: [{ type: 'text', text: 'both are done' }], usage: { input_tokens: 3, output_tokens: 4 } },
    })
    await expect(page.locator('[data-testid=message-bubble-agent]').filter({ hasText: 'both are done' })).toHaveCount(1, { timeout: 10_000 })
    await expect(second, 'after the turn ends').toHaveCount(1)
    await expect(bubbles.filter({ hasText: 'first message' })).toHaveCount(1)

    // It sits where it was typed: after what Claude had said by then, before what came later.
    const order = await page.locator('[data-testid^=message-bubble-]').allTextContents()
    const at = (needle) => order.findIndex((text) => text.includes(needle))
    expect(at('first message')).toBeLessThan(at('second message'))
    expect(at('looking at the first one')).toBeLessThan(at('second message'))
    expect(at('second message')).toBeLessThan(at('still on the first one'))
    expect(at('second message')).toBeLessThan(at('both are done'))

    // A reload brings it back from the record, once.
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible' })
    await expect(page.locator('[data-testid=message-bubble-agent]').filter({ hasText: 'both are done' })).toHaveCount(1, { timeout: 15_000 })
    await expect(second, 'after a reload').toHaveCount(1)
  })

  test('is still one bubble when the screen starts again while it waits, however long Claude takes', async ({ page, request }) => {
    const { seeded, rid, second } = await start(page, request)
    const typedAt = await sendSecond(page)
    await expect(second).toHaveCount(1)

    // Many steps pass before Claude takes the message.
    for (let n = 0; n < 12; n++) step(seeded.jsonl_path, `s${n}-${rid}`, Date.parse(typedAt) + 1000 + n * 100, `step ${n}`)
    const lastStep = page.locator('[data-testid=message-bubble-agent]').filter({ hasText: 'step 11' })
    await expect(lastStep).toHaveCount(1, { timeout: 15_000 })
    await expect(second, 'while it waits').toHaveCount(1)

    // The phone puts the app away and brings it back: the screen starts again from what it kept.
    await page.waitForTimeout(1500)
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible' })
    await expect(lastStep).toHaveCount(1, { timeout: 15_000 })
    await expect(second, 'after the screen starts again, still waiting').toHaveCount(1)

    // Now Claude takes it: more than a minute after the send, so the backend no longer knows
    // which send it was, and the screen has only the text and the time to go by.
    await forgetSends(request)
    queuedHandOver(seeded.jsonl_path, { uuid: `q-${rid}`, text: 'second message', typedAt })
    await expect(second, 'once Claude has taken it').toHaveAttribute('data-cpc-uuid', `q-${rid}`, { timeout: 10_000 })
    await expect(second, 'once Claude has taken it').toHaveCount(1)

    // And once more after another restart of the screen.
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible' })
    await expect(lastStep).toHaveCount(1, { timeout: 15_000 })
    await expect(second, 'after the screen starts once more').toHaveCount(1)
  })
})
