// Golden path: file-tree feature.
// The top bar ⋯ menu has a file-tree entry that mounts the tree modal.

import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'

test.describe('golden: file-tree', () => {
  test('tree modal opens through the top bar menu', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })

    await page.locator('[data-testid=topbar-more-toggle]').click()
    await page.locator('[data-testid=topbar-menu-file-tree]').click()
    await expect(page.locator('[data-testid=file-tree-modal]')).toBeVisible({ timeout: 5_000 })
  })
})
