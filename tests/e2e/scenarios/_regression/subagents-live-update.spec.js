// Regression for the dead subagents watcher (= 2026-07-27, #254/#255 fix chain).
//
// Bug shape: the unified-stream subagents watcher crashed on subscribe with a
// TypeError (a call site missed the #236 signature change), the exception was
// swallowed by the fire-and-forget task, and the modal — while open — never
// received live updates. Completions only appeared after closing and
// reopening the modal (the initial GET still worked). Unit tests now cover
// the watcher itself; this spec pins the full path a user actually sees:
// modal open → agent file appears on disk → the list updates live.
//
// Scenario shape (mirrors bg-fg-resume's "write the file, watch the UI"):
//   1. Seed a session, open the PWA, open the subagents modal (empty).
//   2. Write agent-<id>.jsonl + meta into <jsonl stem>/subagents/ on disk.
//   3. Assert the agent row shows up in the open modal without any reopen.

import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2ebgfg01'

test.describe('regression: subagents live update', () => {
  test('an agent appearing on disk shows up in the open modal', async ({ page, request }) => {
    const seeded = await seedSession(request, 'e2e-bg-fg')
    expect(seeded.sid).toBe(SID)

    await openClient(page, { sid: SID })
    await page.locator('[data-testid=subagents-open-button]').click()
    await expect(page.locator('[data-testid=subagents-modal]')).toBeVisible({ timeout: 5_000 })

    // (2) A subagent transcript lands on disk while the modal is open.
    const base = seeded.jsonl_path.replace(/\.jsonl$/, '')
    const saDir = path.join(base, 'subagents')
    fs.mkdirSync(saDir, { recursive: true })
    fs.writeFileSync(
      path.join(saDir, 'agent-e2elive01.meta.json'),
      JSON.stringify({ agentType: 'general-purpose', description: 'live update probe' }),
    )
    fs.writeFileSync(
      path.join(saDir, 'agent-e2elive01.jsonl'),
      JSON.stringify({
        type: 'assistant', isSidechain: true, uuid: 'sa-1',
        message: { content: [{ type: 'text', text: 'working' }], stop_reason: 'end_turn' },
      }) + '\n',
    )

    // (3) The open modal picks it up live (= watcher push, no reopen).
    await expect(
      page.locator('[data-testid=subagents-modal]').getByText('live update probe'),
    ).toBeVisible({ timeout: 10_000 })
  })
})
