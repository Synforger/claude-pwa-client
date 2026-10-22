// Live: a whole conversation turn through the real parts, in Chromium.
// The microphone is a WAV file (speech, then silence; Chromium plays it on a loop). Voice activity
// detection and Smart Turn run in the page; the listening engine and the Smart Turn model are real.
//
// It runs only when the real parts are given (it is skipped otherwise, as in CI):
//   CPC_E2E_SPEECH_WAV      a WAV of one spoken sentence followed by a few seconds of silence
//   CPC_E2E_SPEECH_TEXT     a word the listening engine should hear in it
//   CPC_E2E_LISTEN_ENGINE   the listening engine (e.g. http://127.0.0.1:10102)
//   CPC_E2E_TURN_MODEL      the Smart Turn model file (e.g. smart-turn-v3.2-cpu.onnx)

import { writeFileSync } from 'node:fs'
import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const WAV = process.env.CPC_E2E_SPEECH_WAV
const LIVE = !!(WAV && process.env.CPC_E2E_SPEECH_TEXT && process.env.CPC_E2E_LISTEN_ENGINE && process.env.CPC_E2E_TURN_MODEL)

test.use({
  launchOptions: {
    args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
      ...(WAV ? [`--use-file-for-fake-audio-capture=${WAV}`] : [])],
  },
})

test.describe('live: voice conversation', () => {
  test.skip(!LIVE, 'needs a speech WAV, a listening engine and a Smart Turn model')
  test.skip(({ browserName }) => browserName !== 'chromium', 'the WAV microphone is a Chromium switch')

  test('what is said is heard, judged finished, written down and sent with the voice mark, to the voice tab even while another tab is shown', async ({ page, request, context }, testInfo) => {
    await context.grantPermissions(['microphone'])
    // Keep a copy of each sound the page sends to be heard (Playwright does not see a Blob body).
    await page.addInitScript(() => {
      window.__heard = []
      const fetch = window.fetch
      window.fetch = async (input, init) => {
        const url = typeof input === 'string' ? input : input.url
        if (url.endsWith('/voice/transcription') && init?.body instanceof Blob) {
          const bytes = new Uint8Array(await init.body.arrayBuffer())
          let text = ''
          for (const b of bytes) text += String.fromCharCode(b)
          window.__heard.push(btoa(text))
        }
        return fetch(input, init)
      }
    })
    const tab = await seedSession(request, 'e2e-voice')
    const other = await seedSession(request, 'e2e-chat-basic')
    const seen = { sent: [], model: [], heard: 0 }
    page.on('request', (r) => {
      if (r.method() === 'POST' && r.url().endsWith('/send')) {
        const sid = decodeURIComponent(new URL(r.url()).pathname.split('/').at(-2))
        seen.sent.push({ sid, text: r.postDataJSON().text, at: Date.now() })
      }
      if (r.method() === 'POST' && r.url().endsWith('/voice/transcription')) seen.heard += 1
    })
    page.on('response', (r) => {
      if (r.url().endsWith('/voice/turn-model')) seen.model.push(r.status())
      if (r.status() >= 400) console.log('[live] HTTP', r.status(), new URL(r.url()).pathname)
    })
    page.on('console', (m) => { if (m.type() === 'warning' || m.type() === 'error') console.log('[page]', m.text().slice(0, 200)) })
    await openClient(page, { sid: tab.sid })

    const button = page.locator('[data-testid=chat-voice-button]')
    await button.click()
    const mic = page.locator('[data-testid=chat-mic-button]')
    await mic.click()
    await expect(mic).toHaveAttribute('data-state', /listening|talking|judging|hearing/, { timeout: 30_000 })
    const listeningAt = Date.now()
    expect(seen.model).toEqual([200])

    const bubble = page.locator('[data-testid=message-bubble-user][data-cpc-optimistic="0"]')
      .filter({ hasText: process.env.CPC_E2E_SPEECH_TEXT })
    await expect(bubble.first()).toBeVisible({ timeout: 45_000 })
    await expect(bubble.first()).not.toContainText('[voice]')
    expect(seen.sent[0].text.startsWith('[voice] ')).toBe(true)
    console.log(`[live] sent "${seen.sent[0].text}" ${seen.sent[0].at - listeningAt} ms after listening began`)
    expect(seen.sent[0].sid).toBe(tab.sid)
    await page.screenshot({ path: testInfo.outputPath('live-conversation.png') })

    // Another tab is shown: the conversation goes on in the voice tab. The WAV plays on a loop from the
    // moment the microphone opened, so the first turn may start part-way through the sentence; the next
    // loop is heard from its start, and is sent to the voice tab, not to the tab on the screen.
    await page.locator('[data-testid=drawer-toggle]').click()
    await page.locator(`[data-testid=session-list-item][data-cpc-sid="${other.sid}"] [data-testid=session-list-item-select]`).click()
    await expect(page.locator('[data-testid=message-bubble-agent]').filter({ hasText: 'Ready for your test.' })).toHaveCount(1)
    await expect.poll(() => seen.sent.length, { timeout: 30_000 }).toBeGreaterThanOrEqual(2)
    console.log(`[live] sent "${seen.sent[1].text}" ${seen.sent[1].at - seen.sent[0].at} ms after the first, to ${seen.sent[1].sid}`)
    expect(seen.sent[1].sid).toBe(tab.sid)
    expect(seen.sent[1].text.startsWith('[voice] ')).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('live-other-tab.png') })

    // Back in the voice tab, what was said while away is there.
    await page.locator('[data-testid=drawer-toggle]').click()
    await page.locator(`[data-testid=session-list-item][data-cpc-sid="${tab.sid}"] [data-testid=session-list-item-select]`).click()
    await expect(bubble).toHaveCount(seen.sent.length, { timeout: 15_000 })
    const heard = await page.evaluate(() => window.__heard)
    heard.forEach((b64, i) => writeFileSync(testInfo.outputPath(`heard-${i + 1}.wav`), Buffer.from(b64, 'base64')))

    await button.click()
    await expect(button).toHaveAttribute('data-state', 'off')
  })
})
