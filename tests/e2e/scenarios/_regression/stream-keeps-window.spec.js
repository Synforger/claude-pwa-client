// Regression: output that keeps flowing into the open conversation must not freeze the chat window.
//
// The chat list puts at most DISPLAY_LIMIT messages in the DOM. Once it is full, each new message drops the oldest
// one off the top. Chrome's scroll anchoring then moves scrollTop by the height of the dropped message, and the
// stick-to-bottom check read that as the user scrolling up: the ↓ button appeared by itself, the window froze, and
// the DOM grew without a bound (100 -> 979 messages in 150 s). The scenario keeps the user at the bottom and
// streams tall messages for long enough for the window to slide many times; the list must stay at DISPLAY_LIMIT and
// the ↓ button must never show.

import { test, expect } from '@playwright/test'
import { appendEvent } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'
import { DISPLAY_LIMIT } from '../../../../frontend/src/_common/displayLimit.js'

const SID = 'ses_e2ewindow'
const TURNS = 160                 // two messages each: more than enough to fill the window twice over
const TURN_INTERVAL_MS = 150
const LINES_PER_MESSAGE = 45      // tall messages: the dropped one is hundreds of pixels

const tallText = (label) => Array.from({ length: LINES_PER_MESSAGE }, (_, i) => `${label} line ${i}`).join('\n\n')

function turnEvents(turn) {
  const stamp = () => new Date().toISOString()
  const toolId = `toolu_window_${turn}`
  return [
    {
      type: 'assistant', uuid: `a-window-${turn}-tool`,
      message: {
        id: `msg_window_${turn}_tool`, role: 'assistant', model: 'claude-opus-4-7', stop_reason: 'tool_use',
        content: [{ type: 'text', text: tallText(`turn ${turn} before`) }, { type: 'tool_use', id: toolId, name: 'Bash', input: { command: 'ls' } }],
      },
      timestamp: stamp(),
    },
    {
      type: 'user', uuid: `u-window-${turn}-result`,
      message: { role: 'user', content: [{ type: 'tool_result', tool_use_id: toolId, content: tallText(`turn ${turn} result`) }] },
      timestamp: stamp(),
    },
    {
      type: 'assistant', uuid: `a-window-${turn}-end`,
      message: { id: `msg_window_${turn}_end`, role: 'assistant', model: 'claude-opus-4-7', stop_reason: 'end_turn', content: [{ type: 'text', text: tallText(`turn ${turn} after`) }] },
      timestamp: stamp(),
    },
  ]
}

test.describe('regression: stream keeps the chat window', () => {
  test('streaming into the open tab at the bottom keeps the list at DISPLAY_LIMIT with no ↓ button', async ({ page, request }) => {
    const seeded = await request.post('/debug/e2e/seed', {
      data: {
        sid: SID, agent_id: 'agent_e2e', account_id: 'e2e', title: 'window',
        jsonl_events: [{ type: 'user', uuid: 'u-window-0', message: { role: 'user', content: 'start' }, timestamp: new Date().toISOString() }],
      },
    })
    expect(seeded.ok()).toBeTruthy()
    const { jsonl_path: jsonlPath } = await seeded.json()
    await openClient(page, { sid: SID })

    const view = () => page.evaluate(() => {
      const list = document.querySelector('.messages')
      return { bubbles: list ? list.children.length : 0, arrowShown: !!document.querySelector('.scroll-btn') }
    })

    let largest = 0
    let arrowSeen = false
    for (let turn = 1; turn <= TURNS; turn++) {
      for (const event of turnEvents(turn)) appendEvent(jsonlPath, event)
      await page.waitForTimeout(TURN_INTERVAL_MS)
      const now = await view()
      largest = Math.max(largest, now.bubbles)
      arrowSeen = arrowSeen || now.arrowShown
    }
    await page.waitForTimeout(1500)
    const end = await view()
    largest = Math.max(largest, end.bubbles)
    arrowSeen = arrowSeen || end.arrowShown

    // The window slid many times: the list was full, and it stayed at the limit (one more for the "thinking" placeholder).
    expect(largest).toBeGreaterThan(DISPLAY_LIMIT - 1)
    expect(largest).toBeLessThanOrEqual(DISPLAY_LIMIT + 1)
    expect(arrowSeen).toBe(false)
  })
})
