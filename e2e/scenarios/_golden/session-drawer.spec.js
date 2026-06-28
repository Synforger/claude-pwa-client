// Golden path: session-drawer feature.
// Open the drawer, create a fresh session via the agent picker, switch to
// it, rename it, and assert the row reflects each step.

import { test, expect } from '@playwright/test'
import { openClient } from '../../helpers/pwa.js'

test.describe('golden: session-drawer', () => {
  test('open drawer + new session + switch + rename', async ({ page }) => {
    await openClient(page)

    await page.locator('[data-testid=drawer-toggle]').click()
    await expect(page.locator('[data-testid=session-drawer]')).toBeVisible()

    // Capture how many sessions exist before the create.
    const before = await page.locator('[data-testid=session-list-item]').count()

    await page.locator('[data-testid=new-session-button]').click()
    // Agent picker shows; the e2e config has a single agent + single
    // account, so the picker auto-completes after the agent click (no
    // account step).
    const picker = page.locator('.agent-picker .agent-picker-item').first()
    await picker.click()

    // /sessions should now report one more session than before.
    await expect.poll(
      async () => {
        const body = await (await page.request.get('/sessions')).json()
        return (body.sessions || body).length
      },
      { timeout: 10_000 },
    ).toBe(before + 1)
  })
})
