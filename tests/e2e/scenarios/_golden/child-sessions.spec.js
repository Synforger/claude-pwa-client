// Golden path: child tabs in the drawer.
// Seed a parent tab with two child tabs (one with a child of its own) and a fork, open the
// drawer, and assert that the parent starts folded and says how many it hides. Open it and
// the child under it: the rows hang under their parent with their marks. What was opened
// survives a reload (= kept per device) and folds again.

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

    // The parent starts folded. Opening it lists its children, and the child that has one of its own starts folded too.
    await expect(row(page, 'ses_e2etreepar')).toContainText('+4')
    for (const tab of TABS.slice(1)) await expect(row(page, tab.sid)).toHaveCount(0)
    await row(page, 'ses_e2etreepar').locator('[data-testid=session-fold]').click()
    await expect(row(page, 'ses_e2etreegc1')).toHaveCount(0)
    await row(page, 'ses_e2etreech1').locator('[data-testid=session-fold]').click()

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

    // The parent renames a child (= what `tabs rename` asks): the list on screen follows it without a reload.
    const renamed = await request.post('/sessions/ses_e2etreepar/children/ses_e2etreech2/title', { form: { title: 'Index the people' } })
    expect(renamed.ok()).toBeTruthy()
    await expect(row(page, 'ses_e2etreech2')).toContainText('Index the people')
  })
})
