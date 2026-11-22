// Golden path: the topbar in its most crowded form still fits a phone. Every button it can show is there at once:
// ⭐, 🎫 with its number, 📋, 📑 (a plan waits for approval), 🖥 (screen sharing is set up) and 🧩. The rightmost button
// must stay on the screen at 375 and 390 px, the widths of the phones the screen is used on.
//
// The plan is put into the tab's status through the e2e door, screen sharing through the e2e localStorage switch, and the
// number through a ticket that asks the operator.

import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'
const PHONE_WIDTHS = [375, 390]

test.describe('golden: topbar', () => {
  test('the most crowded topbar keeps every button on a phone screen', async ({ page, request }, testInfo) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })
    await page.evaluate(() => localStorage.setItem('cpc_e2e_moonlight', '1'))
    await page.reload({ waitUntil: 'domcontentloaded' })

    const opened = await request.post('/tickets', { form: { from: SID, title: 'Crowded topbar', text: 'Asks the operator', due: '' } })
    expect(opened.ok()).toBeTruthy()
    const { id } = await opened.json()
    try {
      const asked = await request.post(`/tickets/${id}/asks`, { form: { from: SID, kind: 'decide', text: 'Which one?', recommend: 'This one' } })
      expect(asked.ok()).toBeTruthy()
      const plan = await request.post(`/debug/e2e/inject-pending-plan/${SID}`, {
        data: { plan: 'do step A', tool_use_id: 'tool_plan_topbar', choices: [{ key: '1', label: 'auto-accept' }] },
      })
      expect(plan.status()).toBe(200)

      await expect(page.locator('[data-testid=plan-approval-open-button]')).toBeVisible({ timeout: 15_000 })
      await expect(page.locator('[data-testid=screenshare-toggle]')).toBeVisible()
      await expect(page.locator('[data-testid=tickets-count]')).toHaveText('1/1', { timeout: 20_000 })

      for (const width of PHONE_WIDTHS) {
        await page.setViewportSize({ width, height: 844 })
        const bar = page.locator('header.topbar')
        const { client, scroll } = await bar.evaluate(el => ({ client: el.clientWidth, scroll: el.scrollWidth }))
        await page.screenshot({ path: testInfo.outputPath(`topbar-crowded-${width}.png`) })
        expect(scroll, `the topbar needs ${scroll} px at ${width} px`).toBeLessThanOrEqual(client)
        const last = await bar.locator(':scope > *').last().boundingBox()
        expect(last.x + last.width).toBeLessThanOrEqual(width)
      }
    } finally {
      const closed = await request.post(`/tickets/${id}/close`, { form: { from: SID, text: 'Done' } })
      expect(closed.ok()).toBeTruthy()   // it waits for the operator, which the next scenario must not see
    }
  })
})
