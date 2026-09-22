// Golden path: attachments feature.
// Use the top bar ⋯ menu's file-attach entry to drive the file chooser, drop a
// tiny PNG in, and assert the attached-images preview surfaces.

import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'

// 1x1 transparent PNG.
const TINY_PNG_B64 =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4XmNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg=='

test.describe('golden: attachments', () => {
  test('attach a PNG via the top bar menu, gallery shows the preview', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })

    const fileChooserPromise = page.waitForEvent('filechooser')
    await page.locator('[data-testid=topbar-more-toggle]').click()
    await page.locator('[data-testid=topbar-menu-file-attach]').click()
    const fileChooser = await fileChooserPromise
    await fileChooser.setFiles({
      name: 'tiny.png',
      mimeType: 'image/png',
      buffer: Buffer.from(TINY_PNG_B64, 'base64'),
    })

    // The draft preview row mounts above ChatInput while a staged
    // attachment is waiting to be sent.
    await expect(page.locator('[data-testid=attachments-bar]')).toBeVisible({ timeout: 5_000 })
  })
})
