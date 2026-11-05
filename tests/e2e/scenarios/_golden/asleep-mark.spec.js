// Golden path: a sleeping tab is marked in the drawer.
// Seed a parent tab with two child tabs and mark one child asleep, the way the sleep of
// backend/sleep/ leaves it. The drawer marks that row with 💤, on load and while it is open:
// a child put to sleep or woken while the list is on screen follows without a reload.

import { test, expect } from '@playwright/test'
import { openClient } from '../../helpers/pwa.js'

const TABS = [
  { sid: 'ses_e2esleeppa', title: 'Sleep parent' },
  { sid: 'ses_e2esleepc1', title: 'Sleep child one', parent_id: 'ses_e2esleeppa', child: true },
  { sid: 'ses_e2esleepc2', title: 'Sleep child two', parent_id: 'ses_e2esleeppa', child: true },
]

const row = (page, sid) => page.locator(`[data-testid=session-list-item][data-cpc-sid="${sid}"]`)
const mark = (page, sid) => row(page, sid).locator('[data-testid=session-asleep]')

test.describe('golden: asleep-mark', () => {
  test('a sleeping tab shows 💤 in the drawer, on load and while the list is open', async ({ page, request }) => {
    for (const tab of TABS) {
      const res = await request.post('/debug/e2e/seed', { data: { agent_id: 'agent_e2e', account_id: 'e2e', jsonl_events: [], ...tab } })
      expect(res.ok()).toBeTruthy()
    }
    const sleep = async (sid, asleep) => {
      const res = await request.post(`/debug/e2e/asleep/${sid}`, { data: { asleep } })
      expect(res.ok()).toBeTruthy()
    }
    await sleep('ses_e2esleepc1', true)

    // On load: the list rows carry `asleep` from GET /sessions.
    await openClient(page, { sid: 'ses_e2esleeppa' })
    await page.locator('[data-testid=drawer-toggle]').click()
    await expect(page.locator('[data-testid=session-drawer]')).toBeVisible()
    await expect(mark(page, 'ses_e2esleepc1')).toBeVisible()
    await expect(mark(page, 'ses_e2esleepc2')).toHaveCount(0)
    await expect(mark(page, 'ses_e2esleeppa')).toHaveCount(0)

    // While the list is open: the overview carries the change.
    await sleep('ses_e2esleepc2', true)
    await expect(mark(page, 'ses_e2esleepc2')).toBeVisible()
    await sleep('ses_e2esleepc1', false)
    await expect(mark(page, 'ses_e2esleepc1')).toHaveCount(0)
    if (process.env.CPC_E2E_SHOT) {
      await page.locator('[data-testid=session-drawer]').screenshot({ path: process.env.CPC_E2E_SHOT })
    }
  })
})
