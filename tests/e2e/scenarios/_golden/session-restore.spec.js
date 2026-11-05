// Golden path: a list restored from the copy an older build kept becomes the tree of the backend's rows.
// A page that iOS brought back wakes with the copy it remembered (= tabs without their tier or child mark) and may
// find the network not back yet. The overview snapshot brings the tiers by itself, but the child mark and the rest
// of a row come only with the list: the rows must be taken from the backend once it answers, at the next overview
// snapshot or when the page comes back to the front. A tab the client moved to another account shows the new account
// at once.

import { test, expect } from '@playwright/test'
import { openClient } from '../../helpers/pwa.js'

// The routes are blocked to fail the way a request fails while the network is not back; a service worker would let
// them past the block.
test.use({ serviceWorkers: 'block' })

const TABS = [
  { sid: 'ses_e2erstpar', title: 'Restore parent', tier: 'projects/Restore Project' },
  { sid: 'ses_e2erstchd', title: 'Restore child', tier: 'projects/Restore Project', parent_id: 'ses_e2erstpar', child: true },
  { sid: 'ses_e2erstnrm', title: 'Restore plain', tier: 'normal' },
]
const PROJECT = 'agent_e2e/Restore Project'

// What an older build kept for these tabs: the tab and its fork link, nothing the backend added later.
const OLD_COPY = TABS.map((tab, at) => ({
  id: tab.sid, agent_id: 'agent_e2e', title: tab.title, created_at: 1 + at, parent_id: tab.parent_id ?? null,
}))

const row = (page, sid) => page.locator(`[data-testid=session-list-item][data-cpc-sid="${sid}"]`)
const folder = (page, key) => page.locator(`[data-testid=session-folder][data-cpc-folder="${key}"]`)

async function seed(request) {
  for (const tab of TABS) {
    const res = await request.post('/debug/e2e/seed', { data: { agent_id: 'agent_e2e', account_id: 'e2e', jsonl_events: [], ...tab } })
    expect(res.ok()).toBeTruthy()
  }
}

// Opens the client with the old copy in place and the list's requests failing, then opens the drawer.
async function openWithOldCopy(page) {
  const gate = { blocked: true }
  await page.addInitScript((copy) => {
    // Only for the first load: the page writes its own copy back later.
    if (sessionStorage.getItem('cpc_e2e_old_copy')) return
    sessionStorage.setItem('cpc_e2e_old_copy', '1')
    localStorage.setItem('cpc_sessions_meta', JSON.stringify(copy))
  }, OLD_COPY)
  await page.route(/\/(sessions|agents)$/, route => (gate.blocked ? route.abort() : route.continue()))
  await openClient(page, { sid: 'ses_e2erstpar' })
  await page.locator('[data-testid=drawer-toggle]').click()
  await expect(page.locator('[data-testid=session-drawer]')).toBeVisible()
  return gate
}

test.describe('golden: session-restore', () => {
  test('while the list does not answer, the tiers come from the overview and the child shows as a fork', async ({ page, request }) => {
    await seed(request)
    await openWithOldCopy(page)
    await expect(row(page, 'ses_e2erstchd')).toBeVisible()
    await expect(folder(page, PROJECT)).toContainText('Restore Project')
    // The copy has no child mark, and nothing but the list brings it.
    await expect(row(page, 'ses_e2erstchd')).toContainText('⑂')
  })

  test('the tree comes out when the page comes back to the front', async ({ page, request }) => {
    await seed(request)
    const gate = await openWithOldCopy(page)
    await expect(row(page, 'ses_e2erstchd')).toContainText('⑂')

    // The network is back, and the page returns to the front.
    gate.blocked = false
    await page.evaluate(() => window.dispatchEvent(new Event('cpc:fg')))

    await expect(row(page, 'ses_e2erstchd')).toContainText('↳')
    await expect(row(page, 'ses_e2erstchd')).not.toContainText('⑂')
    await expect(folder(page, PROJECT)).toContainText('Restore Project')
  })

  test('the foreground report says what the page woke with', async ({ page, request }) => {
    await seed(request)
    await openWithOldCopy(page)
    const reported = page.waitForRequest(req => {
      if (!req.url().endsWith('/log/sw') || req.method() !== 'POST') return false
      const body = req.postDataJSON()
      return body?.stage === 'drawer:tree' && body.trigger === 'foreground'
    })
    await page.evaluate(() => window.dispatchEvent(new Event('cpc:fg')))
    const body = (await reported).postDataJSON()
    // The tiers came with the overview; the child mark has not come, as the list was not answered.
    expect(body).toMatchObject({ trigger: 'foreground', serverAnswered: false, childCount: 0, withTierCount: 3 })
    expect(body.build).toBeTruthy()
  })

  test('a tab moved to another account shows it at once, without fetching the list again', async ({ page, request }) => {
    const created = await request.post('/sessions', { data: { agent_id: 'agent_e2e', account_id: 'e2e', title: 'Moves account' } })
    expect(created.ok()).toBeTruthy()
    const { id } = await created.json()
    await openClient(page, { sid: id })
    await page.locator('[data-testid=drawer-toggle]').click()
    await expect(row(page, id).locator('.drawer-item-account')).toHaveText('E2E')

    const moved = await request.post(`/sessions/${id}/account`, { data: { account_id: 'e2e_ja' } })
    expect(moved.ok()).toBeTruthy()

    await expect(row(page, id).locator('.drawer-item-account')).toHaveText('E2E (Japanese)')
    await request.delete(`/sessions/${id}`)
  })
})
