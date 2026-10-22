// Golden path: the drawer shows the tier each tab's agent started in, next to its account.
// Seed tabs started in different tiers (and one whose tier is not known), open the drawer, and
// assert each row says the last name of its tier. A tab keeps the name the user gave it.

import { test, expect } from '@playwright/test'
import { openClient } from '../../helpers/pwa.js'

const TABS = [
  { sid: 'ses_e2etiernrm', title: 'Plain tab', tier: 'normal' },
  { sid: 'ses_e2etierprj', title: 'Named by the user', tier: 'projects/Agent Platform' },
  { sid: 'ses_e2etiersub', title: 'Deep tab', tier: 'projects/Agent Platform/subprojects/Client' },
  { sid: 'ses_e2etierunk', title: 'Tier not known' },
]

const row = (page, sid) => page.locator(`[data-testid=session-list-item][data-cpc-sid="${sid}"]`)

test.describe('golden: session-tier', () => {
  test('each row names the tier its agent started in, beside the account', async ({ page, request }) => {
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

    const tier = sid => row(page, sid).locator('[data-testid=session-tier]')
    await expect(tier('ses_e2etiernrm')).toHaveText('normal')
    await expect(tier('ses_e2etierprj')).toHaveText('Agent Platform')
    await expect(tier('ses_e2etiersub')).toHaveText('Client')
    await expect(tier('ses_e2etierunk')).toHaveCount(0)
    // The account label stays, and the name of the tab is the one it was given.
    await expect(row(page, 'ses_e2etierprj')).toContainText('E2E')
    await expect(row(page, 'ses_e2etierprj').locator('.drawer-item-title')).toHaveText('Named by the user')
    if (process.env.CPC_E2E_SHOT) {
      await page.screenshot({ path: process.env.CPC_E2E_SHOT })
    }
  })
})
