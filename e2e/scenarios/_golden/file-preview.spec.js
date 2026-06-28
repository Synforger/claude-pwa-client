// Golden path: file-preview feature.
// Inject a favorites entry pointing at the repo's own README, open the
// favorites quick picker, click the entry, assert the preview modal mounts
// with the right path.

import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'

test.describe('golden: file-preview', () => {
  test('preview modal opens from favorites quick picker', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })

    // Pin a favorite to a file the backend will happily serve under HOME.
    const fixturePath = process.env.HOME + '/repos/claude-pwa-client.v2/README.md'
    await page.evaluate((path) => {
      localStorage.setItem('cpc.fileTree.favorites', JSON.stringify([{ path, name: 'README.md' }]))
      window.dispatchEvent(new CustomEvent('cpc-favorites-changed'))
    }, fixturePath)
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible' })
    await page.waitForTimeout(1500)

    await page.locator('[data-testid=favorites-open-button]').click()
    // The favorites picker shows the pinned row; click it.
    await page.getByText('README.md').first().click()

    const modal = page.locator('[data-testid=file-preview-modal]')
    await expect(modal).toBeVisible({ timeout: 10_000 })
    await expect(modal.locator('[data-testid=file-preview-path]')).toContainText('README.md')
  })
})
