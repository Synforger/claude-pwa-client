// Golden path: file-tree feature.
// ChatInput's overflow menu has a "ファイルツリー" entry that mounts the tree modal.

import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'

test.describe('golden: file-tree', () => {
  test('tree modal opens through the chat menu', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })

    await page.locator('[data-testid=chat-menu-toggle]').click()
    await page.getByRole('button', { name: 'ファイルツリー' }).click()
    await expect(page.locator('[data-testid=file-tree-modal]')).toBeVisible({ timeout: 5_000 })
  })
})
