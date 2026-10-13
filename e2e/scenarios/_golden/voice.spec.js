// Golden path: voice.
// A tab whose agent has a voice shows a 🔊 toggle in the topbar. While it is on, a reply
// that newly arrives is cut into sentences and each sentence is fetched as sound and
// played, in order. What was already there is not said, and turning it off stops it.
// A mark at the head of a sentence says how to say it, and is not shown in the bubble.
//
// The speech engine is the test backend's own fixture (silence for every sentence, and a
// refusal for a sentence that starts with "[fail]"), so the whole path runs: screen ->
// voice endpoints -> engine. Whether a real engine sounds right is not something a
// browser test can tell.

import { test, expect } from '@playwright/test'
import { seedSession, appendEvent } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const toggle = '[data-testid=voice-toggle]'

// A reply of the agent's, written to the tab's record the way Claude writes one.
function reply(jsonlPath, id, content) {
  appendEvent(jsonlPath, {
    type: 'assistant', uuid: `a-voice-${id}`, timestamp: new Date().toISOString(),
    message: { id: `msg_voice_${id}`, role: 'assistant', stop_reason: 'end_turn', content },
  })
}
const text = (t) => ({ type: 'text', text: t })

test.describe('golden: voice', () => {
  test.beforeEach(async ({ page }) => {
    // Count the sounds the page actually starts, and the ones it cuts short.
    await page.addInitScript(() => {
      window.__voice = { started: 0, stopped: 0 }
      const Node = window.AudioBufferSourceNode
      const start = Node.prototype.start
      const stop = Node.prototype.stop
      Node.prototype.start = function (...args) { window.__voice.started += 1; return start.apply(this, args) }
      Node.prototype.stop = function (...args) { window.__voice.stopped += 1; return stop.apply(this, args) }
    })
  })

  test('a tab whose agent has no voice shows no toggle', async ({ page, request }) => {
    const plain = await seedSession(request, 'e2e-chat-basic')
    await openClient(page, { sid: plain.sid })
    await expect(page.locator(toggle)).toHaveCount(0)
  })

  test('new replies are said sentence by sentence while the toggle is on', async ({ page, request }, testInfo) => {
    const tab = await seedSession(request, 'e2e-voice')
    const asked = { utterances: [], synthesis: [] }
    page.on('request', (r) => {
      if (r.method() !== 'POST') return
      if (r.url().endsWith('/voice/utterances')) asked.utterances.push(r.postDataJSON().text)
      if (r.url().endsWith('/voice/synthesis')) asked.synthesis.push(r.postDataJSON())
    })
    await openClient(page, { sid: tab.sid })
    const started = () => page.evaluate(() => window.__voice.started)

    // Off to begin with, and what arrives while it is off is not said.
    await expect(page.locator(toggle)).toBeVisible()
    await expect(page.locator(toggle)).toHaveAttribute('aria-pressed', 'false')
    reply(tab.jsonl_path, 'off', [text('Written while the voice was off.')])
    await expect(page.locator('[data-testid=message-bubble-agent]').filter({ hasText: 'while the voice was off' }))
      .toHaveCount(1, { timeout: 20_000 })
    expect(asked.utterances).toEqual([])
    await page.screenshot({ path: testInfo.outputPath('voice-off.png') })

    // On: nothing that was already there is said.
    await page.locator(toggle).click()
    await expect(page.locator(toggle)).toHaveAttribute('aria-pressed', 'true')
    await page.waitForTimeout(1500)
    expect(asked.utterances).toEqual([])
    expect(await started()).toBe(0)

    // A reply arrives: its sentences are fetched and played, code and paths left out.
    reply(tab.jsonl_path, 'first', [
      text('[happy] Done! The tests pass.\nThe notes are in `~/notes/voice.md`.\n```\nnot said\n```'),
    ])
    await expect.poll(started, { timeout: 20_000 }).toBe(3)
    expect(asked.utterances).toHaveLength(1)
    expect(asked.synthesis).toEqual([
      { mark: 'happy', text: 'Done!' },
      { mark: 'happy', text: 'The tests pass.' },
      { mark: 'calm', text: 'The notes are in .' },
    ])
    await expect(page.locator('[data-testid=voice-error]')).toHaveCount(0)
    // The mark is for the voice: the bubble shows the reply without it.
    const said = page.locator('[data-testid=message-bubble-agent]').filter({ hasText: 'The tests pass.' })
    await expect(said).toHaveCount(1)
    await expect(said).toContainText('Done! The tests pass.')
    await expect(said).not.toContainText('[happy]')
    await page.screenshot({ path: testInfo.outputPath('voice-on.png') })

    // What a tool call says it does is said too; the call itself is not.
    reply(tab.jsonl_path, 'tool', [
      { type: 'tool_use', id: 'tool_voice_1', name: 'Bash', input: { command: 'ls -la', description: 'List the files here' } },
    ])
    await expect.poll(started, { timeout: 20_000 }).toBe(4)
    expect(asked.synthesis.at(-1)).toEqual({ mark: 'calm', text: 'List the files here' })

    // A reload turns it off again (sound needs a press), and brings nothing back to be said.
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible', timeout: 15_000 })
    await expect(page.locator(toggle)).toHaveAttribute('aria-pressed', 'false')
    await page.locator(toggle).click()
    await page.waitForTimeout(1500)
    expect(await started()).toBe(0)
  })

  test('a sentence the engine refuses shows why under the toggle, and off clears it', async ({ page, request }, testInfo) => {
    const tab = await seedSession(request, 'e2e-voice')
    await openClient(page, { sid: tab.sid })
    await page.locator(toggle).click()
    await expect(page.locator(toggle)).toHaveAttribute('aria-pressed', 'true')

    reply(tab.jsonl_path, 'fail', [text('[fail] the engine refuses this one! This one is never asked!')])
    const error = page.locator('[data-testid=voice-error]')
    await expect(error).toBeVisible({ timeout: 20_000 })
    await expect(error).toContainText('synthesis')
    await expect(error).toContainText('500')
    expect(await page.evaluate(() => window.__voice.started)).toBe(0)
    await page.screenshot({ path: testInfo.outputPath('voice-error.png') })
    await page.setViewportSize({ width: 390, height: 844 })
    await expect(error).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('voice-error-narrow.png') })

    // The next reply is said, and the error goes away once a sentence has played.
    reply(tab.jsonl_path, 'after', [text('This one plays.')])
    await expect.poll(() => page.evaluate(() => window.__voice.started), { timeout: 20_000 }).toBe(1)
    await expect(error).toHaveCount(0)

    await page.locator(toggle).click()
    await expect(page.locator(toggle)).toHaveAttribute('aria-pressed', 'false')
    reply(tab.jsonl_path, 'silent', [text('Not said: the voice is off.')])
    await expect(page.locator('[data-testid=message-bubble-agent]').filter({ hasText: 'the voice is off' }))
      .toHaveCount(1, { timeout: 20_000 })
    expect(await page.evaluate(() => window.__voice.started)).toBe(1)
  })
})
