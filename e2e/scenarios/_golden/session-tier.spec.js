// Golden path: the drawer lists each tab in the folder of the tier its agent started in.
// Seed tabs started in different tiers (and one whose tier is not known), open the drawer, and
// assert the folders and what sits in them; folding a folder hides its tabs and says how many it holds.
// A tab keeps the name the user gave it, and its account label.

import { test, expect } from '@playwright/test'
import { openClient } from '../../helpers/pwa.js'

const TABS = [
  { sid: 'ses_e2etiernrm', title: 'Plain tab', tier: 'normal' },
  { sid: 'ses_e2etierprj', title: 'Named by the user', tier: 'projects/Agent Platform' },
  { sid: 'ses_e2etiersub', title: 'Deep tab', tier: 'projects/Agent Platform/subprojects/Client' },
  { sid: 'ses_e2etierunk', title: 'Tier not known' },
]
const PROJECT = 'agent_e2e/Agent Platform'
const SUBPROJECT = 'agent_e2e/Agent Platform/Client'

const row = (page, sid) => page.locator(`[data-testid=session-list-item][data-cpc-sid="${sid}"]`)
const folder = (page, key) => page.locator(`[data-testid=session-folder][data-cpc-folder="${key}"]`)

test.describe('golden: session-tier', () => {
  test('each tab sits in the folder of the tier its agent started in, and a folder folds', async ({ page, request }) => {
    for (const tab of TABS) {
      const res = await request.post('/debug/e2e/seed', { data: { agent_id: 'agent_e2e', account_id: 'e2e', jsonl_events: [], ...tab } })
      expect(res.ok()).toBeTruthy()
    }
    const listed = Object.fromEntries((await (await request.get('/sessions')).json()).map(s => [s.id, s.tier]))
    expect(listed).toMatchObject({
      ses_e2etiernrm: 'normal',
      ses_e2etierprj: 'projects/Agent Platform',
      ses_e2etiersub: 'projects/Agent Platform/subprojects/Client',
      ses_e2etierunk: null,
    })

    await openClient(page, { sid: 'ses_e2etiernrm' })
    await page.locator('[data-testid=drawer-toggle]').click()
    await expect(page.locator('[data-testid=session-drawer]')).toBeVisible()

    await expect(folder(page, PROJECT)).toContainText('Agent Platform')
    await expect(folder(page, SUBPROJECT)).toContainText('Client')
    // Each folder comes right before what it holds: the project's tab, then the subproject's folder and tab.
    const order = await page.locator('[data-testid=session-folder], [data-testid=session-list-item]').evaluateAll(
      nodes => nodes.map(n => n.dataset.cpcFolder || n.dataset.cpcSid),
    )
    const at = id => order.indexOf(id)
    expect(at(PROJECT)).toBeLessThan(at('ses_e2etierprj'))
    expect(at('ses_e2etierprj')).toBeLessThan(at(SUBPROJECT))
    expect(at(SUBPROJECT)).toBeLessThan(at('ses_e2etiersub'))
    // A tab in the agent's own folder (or whose tier is not known) stays before every folder.
    expect(at('ses_e2etiernrm')).toBeLessThan(at(PROJECT))
    expect(at('ses_e2etierunk')).toBeLessThan(at(PROJECT))
    // The account label stays, and the name of the tab is the one it was given.
    await expect(row(page, 'ses_e2etierprj')).toContainText('E2E')
    await expect(row(page, 'ses_e2etierprj').locator('.drawer-item-title')).toHaveText('Named by the user')
    if (process.env.CPC_E2E_SHOT) {
      await page.screenshot({ path: process.env.CPC_E2E_SHOT })
    }

    await folder(page, PROJECT).click()
    await expect(folder(page, PROJECT)).toHaveAttribute('aria-expanded', 'false')
    await expect(folder(page, PROJECT)).toContainText('2')
    await expect(row(page, 'ses_e2etierprj')).toHaveCount(0)
    await expect(row(page, 'ses_e2etiersub')).toHaveCount(0)
    await expect(folder(page, SUBPROJECT)).toHaveCount(0)
    await expect(row(page, 'ses_e2etiernrm')).toBeVisible()
    if (process.env.CPC_E2E_SHOT_FOLDED) {
      await page.screenshot({ path: process.env.CPC_E2E_SHOT_FOLDED })
    }
  })
})
