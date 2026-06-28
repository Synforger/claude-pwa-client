// Golden path: subagents feature.
// Topbar 🤖 button opens the subagents modal.

import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'

test.describe('golden: subagents', () => {
  test('subagents modal opens via the topbar 🤖 button', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })

    await page.locator('[data-testid=subagents-open-button]').click()
    await expect(page.locator('[data-testid=subagents-modal]')).toBeVisible({ timeout: 5_000 })
  })
})
