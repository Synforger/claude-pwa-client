// Golden path: child tabs in the drawer.
// Seed a parent tab with two child tabs (one with a child of its own) and a fork, open the
// drawer, and assert the rows hang under their parent with their marks. Fold the parent:
// the rows under it leave the list and the parent says how many it hides. The fold
// survives a reload (= kept per device) and unfolds again.

import { test, expect } from '@playwright/test'
import { openClient } from '../../helpers/pwa.js'

const TABS = [
  { sid: 'ses_e2etreepar', title: 'Tree parent' },
  { sid: 'ses_e2etreech1', title: 'Tree child one', parent_id: 'ses_e2etreepar', child: true },
  { sid: 'ses_e2etreech2', title: 'Tree child two', parent_id: 'ses_e2etreepar', child: true },
  { sid: 'ses_e2etreegc1', title: 'Tree grandchild', parent_id: 'ses_e2etreech1', child: true },
  { sid: 'ses_e2etreefrk', title: 'Tree fork', parent_id: 'ses_e2etreepar' },
]

const row = (page, sid) => page.locator(`[data-testid=session-list-item][data-cpc-sid="${sid}"]`)

test.describe('golden: child-sessions', () => {
  test('child tabs hang under their parent, and the parent folds them', async ({ page, request }) => {
    for (const tab of TABS) {
      const res = await request.post('/debug/e2e/seed', { data: { agent_id: 'agent_e2e', account_id: 'e2e', jsonl_events: [], ...tab } })
      expect(res.ok()).toBeTruthy()
    }
    await openClient(page, { sid: 'ses_e2etreepar' })
    await page.locator('[data-testid=drawer-toggle]').click()
    await expect(page.locator('[data-testid=session-drawer]')).toBeVisible()

    // Every row under the parent is listed, a child with ↳ and the fork with ⑂.
    for (const tab of TABS) await expect(row(page, tab.sid)).toBeVisible()
    await expect(row(page, 'ses_e2etreech1')).toContainText('↳')
    await expect(row(page, 'ses_e2etreefrk')).toContainText('⑂')
    await expect(row(page, 'ses_e2etreech2')).not.toContainText('⑂')

    const fold = row(page, 'ses_e2etreepar').locator('[data-testid=session-fold]')
    await expect(fold).toHaveAttribute('aria-expanded', 'true')
    await fold.click()
    for (const tab of TABS.slice(1)) await expect(row(page, tab.sid)).toHaveCount(0)
    await expect(row(page, 'ses_e2etreepar')).toContainText('+4')
    if (process.env.CPC_E2E_SHOT_FOLDED) {
      await page.locator('[data-testid=session-drawer]').screenshot({ path: process.env.CPC_E2E_SHOT_FOLDED })
    }

    // Kept per device: still folded after a reload.
    await openClient(page, { sid: 'ses_e2etreepar' })
    await page.locator('[data-testid=drawer-toggle]').click()
    await expect(row(page, 'ses_e2etreech1')).toHaveCount(0)
    await expect(row(page, 'ses_e2etreepar').locator('[data-testid=session-fold]')).toHaveAttribute('aria-expanded', 'false')

    await row(page, 'ses_e2etreepar').locator('[data-testid=session-fold]').click()
    for (const tab of TABS) await expect(row(page, tab.sid)).toBeVisible()
    if (process.env.CPC_E2E_SHOT) {
      await page.locator('[data-testid=session-drawer]').screenshot({ path: process.env.CPC_E2E_SHOT })
    }
  })
})
