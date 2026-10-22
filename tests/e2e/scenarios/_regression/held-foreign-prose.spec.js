// Regression: an English reply reached the screen in a tab whose Claude Code settings ask for Japanese.
//
// A hook can make Claude say an English reply again in Japanese, but only after the reply was written
// to the record, and the screen showed every text block as soon as it was written. So the English reply
// was read in full before the Japanese one arrived, and stayed on screen after it.
// The backend now turns such prose into a held_text block (= backend/_common/prose_language.py), and the
// screen folds it closed, both for the history and for lines that arrive while the tab is open.

import { test, expect } from '@playwright/test'
import { appendFileSync } from 'node:fs'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2eheldpro'
const ENGLISH = 'The fix is ready. The only thing left before I merge and deploy it is the GitHub check, which has not finished yet.'
const ENGLISH_LATER = 'I have read the documentation for both devices, and the streams can be subscribed to once the headset is connected.'
const JAPANESE = '直しを作り終えました。 GitHub の検査が終わるのを待ってから merge して、 本番に入れます。'

const at = (n) => new Date(Date.UTC(2026, 0, 1, 0, 0, n)).toISOString()
const reply = (n, text) => ({
  type: 'assistant', uuid: `a-held-${n}`,
  message: { id: `msg_held_${n}`, role: 'assistant', model: 'claude-opus-4-7', stop_reason: 'end_turn',
    content: [{ type: 'text', text }] },
  timestamp: at(n),
})

test.describe('regression: prose not in the configured language is folded', () => {
  test('English replies are folded closed, the Japanese one is shown, from history and live', async ({ page, request }, testInfo) => {
    const res = await request.post('/debug/e2e/seed', {
      data: {
        sid: SID, agent_id: 'agent_e2e', account_id: 'e2e_ja', title: 'held prose',
        jsonl_events: [
          { type: 'user', uuid: 'u-held-1', message: { role: 'user', content: '直った？' }, timestamp: at(1) },
          reply(2, ENGLISH),
          reply(3, JAPANESE),
        ],
      },
    })
    expect(res.ok()).toBeTruthy()
    const { jsonl_path: jsonlPath } = await res.json()

    await openClient(page, { sid: SID })
    await expect(page.getByText(JAPANESE)).toBeVisible({ timeout: 15_000 })
    const held = page.locator('[data-testid=held-prose]')
    await expect(held).toHaveCount(1)
    await expect(page.getByText(ENGLISH)).toBeHidden()

    // A line written while the tab is open comes through the live stream, not the history.
    appendFileSync(jsonlPath, JSON.stringify({ type: 'user', uuid: 'u-held-4', message: { role: 'user', content: '次は？' }, timestamp: at(4) }) + '\n')
    appendFileSync(jsonlPath, JSON.stringify(reply(5, ENGLISH_LATER)) + '\n')
    await expect(held).toHaveCount(2, { timeout: 15_000 })
    await expect(page.getByText(ENGLISH_LATER)).toBeHidden()
    await page.screenshot({ path: testInfo.outputPath('held-closed.png') })

    // Tapping the fold shows the whole text.
    await held.first().locator('summary').click()
    await expect(page.getByText(ENGLISH)).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('held-open.png') })
  })
})
