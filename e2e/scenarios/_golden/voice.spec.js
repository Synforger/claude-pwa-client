// Golden path: voice.
// A tab whose agent has a voice shows one conversation button in the input row (and nothing
// in the topbar). While the conversation is open, a reply that newly arrives is cut into
// sentences and each sentence is fetched as sound and played, in order. What was already
// there is not said, and closing the conversation stops it. A mark at the head of a sentence
// says how to say it, and is not shown in the bubble. What the person types while it is open
// goes with a `[voice]` mark at its head, so the agent knows the reply will be heard; the
// bubble does not show that mark either.
// Opening the conversation of an agent that listens loads the listening parts (voice activity
// detection in the page) and starts listening to the microphone; closing it lets the
// microphone go. What is said, judged and written down is the live scenario's to check
// (scenarios/live/voice-conversation.spec.js): a tone cannot stand in for speech.
//
// The speech engine is the test backend's own fixture (silence for every sentence, and a
// refusal for a sentence that starts with "[fail]"), so the whole path runs: screen ->
// voice endpoints -> engine. Whether a real engine sounds right is not something a
// browser test can tell.

import { readFileSync } from 'node:fs'
import { test, expect } from '@playwright/test'
import { seedSession, appendEvent } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const button = '[data-testid=chat-voice-button]'
const micButton = '[data-testid=chat-mic-button]'

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
    await page.addInitScript(() => {
      // Count the sounds the page actually starts, and the ones it cuts short.
      window.__voice = { started: 0, stopped: 0, mics: [] }
      const Node = window.AudioBufferSourceNode
      const start = Node.prototype.start
      const stop = Node.prototype.stop
      Node.prototype.start = function (...args) { window.__voice.started += 1; return start.apply(this, args) }
      Node.prototype.stop = function (...args) { window.__voice.stopped += 1; return stop.apply(this, args) }
      // A tone from WebAudio stands in for the microphone (the same in every browser this runs).
      // It is put on the prototype: WebKit silently ignores an assignment on navigator.mediaDevices.
      Object.defineProperty(MediaDevices.prototype, 'getUserMedia', {
        configurable: true,
        writable: true,
        value: async () => {
          const ctx = new AudioContext()
          const tone = ctx.createOscillator()
          const out = ctx.createMediaStreamDestination()
          tone.connect(out)
          tone.start()
          window.__voice.mics.push(...out.stream.getTracks())
          return out.stream
        },
      })
    })
  })

  test('a tab whose agent has no voice shows no conversation button', async ({ page, request }) => {
    const plain = await seedSession(request, 'e2e-chat-basic')
    await openClient(page, { sid: plain.sid })
    await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible' })
    await expect(page.locator(button)).toHaveCount(0)
  })

  test('new replies are said sentence by sentence while the conversation is open', async ({ page, request }, testInfo) => {
    const tab = await seedSession(request, 'e2e-voice')
    const asked = { utterances: [], synthesis: [] }
    page.on('request', (r) => {
      if (r.method() !== 'POST') return
      if (r.url().endsWith('/voice/utterances')) asked.utterances.push(r.postDataJSON().text)
      if (r.url().endsWith('/voice/synthesis')) asked.synthesis.push(r.postDataJSON())
    })
    await openClient(page, { sid: tab.sid })
    const started = () => page.evaluate(() => window.__voice.started)

    // Closed to begin with, nothing in the topbar, and what arrives while it is closed is not said.
    await expect(page.locator(button)).toBeVisible()
    await expect(page.locator(button)).toHaveAttribute('aria-pressed', 'false')
    await expect(page.locator('[data-testid=voice-toggle]')).toHaveCount(0)
    reply(tab.jsonl_path, 'off', [text('Written while the voice was off.')])
    await expect(page.locator('[data-testid=message-bubble-agent]').filter({ hasText: 'while the voice was off' }))
      .toHaveCount(1, { timeout: 20_000 })
    expect(asked.utterances).toEqual([])
    await page.screenshot({ path: testInfo.outputPath('voice-off.png') })

    // Open: nothing that was already there is said.
    await page.locator(button).click()
    await expect(page.locator(button)).toHaveAttribute('aria-pressed', 'true')
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

    // A tool call is not said, nor what it says it does; the words written after it are.
    reply(tab.jsonl_path, 'tool', [
      { type: 'tool_use', id: 'tool_voice_1', name: 'Bash', input: { command: 'ls -la', description: 'List the files here' } },
    ])
    reply(tab.jsonl_path, 'between', [{ type: 'text', text: 'Three files.' }])
    await expect.poll(started, { timeout: 20_000 }).toBe(4)
    expect(asked.synthesis.at(-1)).toEqual({ mark: 'calm', text: 'Three files.' })
    expect(asked.synthesis.map((u) => u.text)).not.toContain('List the files here')

    // A reload closes it again (sound needs a press), and brings nothing back to be said.
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible', timeout: 15_000 })
    await expect(page.locator(button)).toHaveAttribute('aria-pressed', 'false')
    await page.locator(button).click()
    await page.waitForTimeout(1500)
    expect(await started()).toBe(0)
  })

  test('what is typed while the conversation is open reaches the agent with a voice mark, which the bubble hides', async ({ page, request }, testInfo) => {
    const tab = await seedSession(request, 'e2e-voice')
    const sent = []
    page.on('request', (r) => {
      if (r.method() === 'POST' && r.url().endsWith('/send')) sent.push(r.postDataJSON().text)
    })
    await openClient(page, { sid: tab.sid })
    const input = page.locator('[data-testid=chat-input]')
    const confirmed = (hasText) => page.locator('[data-testid=message-bubble-user][data-cpc-optimistic="0"]').filter({ hasText })

    // Closed: the text goes as it was typed.
    await input.fill('typed while the voice is off')
    await page.locator('[data-testid=chat-send-button]').click()
    await expect(confirmed('typed while the voice is off')).toHaveCount(1, { timeout: 15_000 })
    expect(sent).toEqual(['typed while the voice is off'])

    // Open: the agent is told the reply will be heard; the record keeps the mark, the bubble does not show it.
    await page.locator(button).click()
    await expect(page.locator(button)).toHaveAttribute('aria-pressed', 'true')
    await input.fill('typed while the voice is on')
    await page.locator('[data-testid=chat-send-button]').click()
    const bubble = confirmed('typed while the voice is on')
    await expect(bubble).toHaveCount(1, { timeout: 15_000 })
    expect(sent.at(-1)).toBe('[voice] typed while the voice is on')
    await expect(bubble).not.toContainText('[voice]')
    expect(readFileSync(tab.jsonl_path, 'utf8')).toContain('[voice] typed while the voice is on')
    await page.screenshot({ path: testInfo.outputPath('voice-typed.png') })
  })

  test('turning the voice on leaves the microphone alone; the microphone button takes it, and closing or turning the voice off lets it go', async ({ page, request }, testInfo) => {
    const tab = await seedSession(request, 'e2e-voice')
    const loaded = []
    page.on('response', (r) => {
      const path = new URL(r.url()).pathname
      if (path.startsWith('/assets/voice-') || path.endsWith('/voice/conversation')) loaded.push(`${r.status()} ${path}`)
    })
    await openClient(page, { sid: tab.sid })
    const mics = () => page.evaluate(() => window.__voice.mics.map((t) => t.readyState))

    await expect(page.locator(micButton)).toHaveCount(0)
    await page.locator(button).click()
    await expect(page.locator(button)).toHaveAttribute('data-state', 'on')
    // The voice alone takes no microphone: only the voice plays.
    await expect(page.locator(micButton)).toHaveAttribute('data-state', 'muted')
    await expect(page.locator(micButton)).toHaveAttribute('aria-pressed', 'false')
    expect(await mics()).toEqual([])
    expect(loaded.some((l) => l.endsWith('/voice/conversation'))).toBe(false)
    await page.screenshot({ path: testInfo.outputPath('voice-only.png') })

    // The microphone button takes the microphone.
    await page.locator(micButton).click()
    await expect(page.locator(micButton)).toHaveAttribute('data-state', 'listening', { timeout: 30_000 })
    await expect(page.locator('[data-testid=voice-error]')).toHaveCount(0)
    expect(await mics()).toEqual(['live'])
    // The voice activity model and the model runtime came from the build; this screen holds the conversation.
    for (const part of ['silero_vad_v5.onnx', 'ort-wasm-simd-threaded.wasm']) {
      expect(loaded.some((l) => l.startsWith('200 ') && l.endsWith(part)), part).toBe(true)
    }
    expect(loaded.some((l) => l.startsWith('200 ') && l.endsWith('/voice/conversation'))).toBe(true)
    // The audio worklet is fetched from the worklet's own scope, out of the page's sight: it is served next to the model.
    const model = loaded.find((l) => l.endsWith('silero_vad_v5.onnx')).split(' ')[1]
    const worklet = await request.get(model.replace('silero_vad_v5.onnx', 'vad.worklet.bundle.min.js'))
    expect(worklet.status()).toBe(200)
    expect(worklet.headers()['content-type']).toMatch(/javascript/)
    await page.screenshot({ path: testInfo.outputPath('voice-listening.png') })

    // Closing the microphone lets it go and keeps the voice on.
    await page.locator(micButton).click()
    await expect(page.locator(micButton)).toHaveAttribute('data-state', 'muted')
    await expect(page.locator(micButton)).toHaveAttribute('aria-pressed', 'false')
    await expect(page.locator(button)).toHaveAttribute('data-state', 'on')
    await expect.poll(mics, { timeout: 5_000 }).toEqual(['ended'])
    await page.screenshot({ path: testInfo.outputPath('voice-muted.png') })

    // Opening it again listens on a new microphone.
    await page.locator(micButton).click()
    await expect(page.locator(micButton)).toHaveAttribute('data-state', 'listening', { timeout: 30_000 })
    await expect.poll(mics, { timeout: 5_000 }).toEqual(['ended', 'live'])

    // Turning the voice off closes everything, and the microphone button goes.
    await page.locator(button).click()
    await expect(page.locator(button)).toHaveAttribute('data-state', 'off')
    await expect(page.locator(micButton)).toHaveCount(0)
    await expect.poll(mics, { timeout: 5_000 }).toEqual(['ended', 'ended'])

    // The microphone was left open, so the next time the voice is turned on, it takes the microphone again.
    await page.locator(button).click()
    await expect(page.locator(micButton)).toHaveAttribute('data-state', 'listening', { timeout: 30_000 })
    await expect.poll(mics, { timeout: 5_000 }).toEqual(['ended', 'ended', 'live'])
  })

  test('the voice goes on in its tab while another tab is shown, until the voice is turned on in another tab', async ({ page, request }, testInfo) => {
    const tab = await seedSession(request, 'e2e-voice')
    const other = await seedSession(request, 'e2e-chat-basic')
    const second = await seedSession(request, 'e2e-voice-second')
    await openClient(page, { sid: tab.sid })
    const started = () => page.evaluate(() => window.__voice.started)
    const mics = () => page.evaluate(() => window.__voice.mics.map((t) => t.readyState))
    const show = async (sid) => {
      await page.locator('[data-testid=drawer-toggle]').click()
      await page.locator(`[data-testid=session-list-item][data-cpc-sid="${sid}"] [data-testid=session-list-item-select]`).click()
    }

    await page.locator(button).click()
    await page.locator(micButton).click()
    await expect(page.locator(micButton)).toHaveAttribute('data-state', 'listening', { timeout: 30_000 })

    // Another tab is shown: the microphone stays open, and a reply in the voice tab is said.
    await show(other.sid)
    await expect(page.locator('[data-testid=message-bubble-agent]').filter({ hasText: 'Ready for your test.' })).toHaveCount(1)
    await expect(page.locator(button)).toHaveCount(0)
    expect(await mics()).toEqual(['live'])
    reply(tab.jsonl_path, 'away', [text('Said while another tab is shown.')])
    await expect.poll(started, { timeout: 20_000 }).toBe(1)
    await page.screenshot({ path: testInfo.outputPath('voice-other-tab.png') })

    // Back in the voice tab, the voice is still on and the microphone still listens.
    await show(tab.sid)
    await expect(page.locator(button)).toHaveAttribute('data-state', 'on')
    await expect(page.locator(micButton)).toHaveAttribute('data-state', 'listening')

    // Turning the voice on in another tab closes the first: one tab holds the voice.
    await show(second.sid)
    await expect(page.locator(button)).toHaveAttribute('data-state', 'off')
    await page.locator(button).click()
    await expect(page.locator(button)).toHaveAttribute('data-state', 'on')
    await expect.poll(mics, { timeout: 5_000 }).toEqual(['ended'])
    reply(tab.jsonl_path, 'closed', [text('Not said once the voice moved.')])
    await page.waitForTimeout(1500)
    expect(await started()).toBe(1)
    await show(tab.sid)
    await expect(page.locator(button)).toHaveAttribute('data-state', 'off')
  })

  test('a sentence the engine refuses shows why above the button, and closing clears it', async ({ page, request }, testInfo) => {
    const tab = await seedSession(request, 'e2e-voice')
    await openClient(page, { sid: tab.sid })
    await page.locator(button).click()
    await expect(page.locator(button)).toHaveAttribute('aria-pressed', 'true')

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

    await page.locator(button).click()
    await expect(page.locator(button)).toHaveAttribute('aria-pressed', 'false')
    reply(tab.jsonl_path, 'silent', [text('Not said: the voice is off.')])
    await expect(page.locator('[data-testid=message-bubble-agent]').filter({ hasText: 'the voice is off' }))
      .toHaveCount(1, { timeout: 20_000 })
    expect(await page.evaluate(() => window.__voice.started)).toBe(1)
  })
})
