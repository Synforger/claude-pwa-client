// Regression: an attached image is shown by one URL, and that URL is a thumbnail.
//
// Chrome keeps a decoded copy of every picture it is shown by a blob URL, and keeps it after the <img> is gone and the
// URL revoked. A bubble that made a new URL on each mount (a conversation switched to and back) decoded the same image
// again each time, and the attachment bar showed the picked file by a second URL, so every image was decoded twice
// before it was ever shown again: the copies piled up in the renderer's memory until the screen was reloaded.
//
// Scenario shape:
//   1. Pick a 1000 × 700 PNG into session A. The attachment bar shows it.
//   2. Send. The bubble shows the same image by the same URL as the bar did, and the picture behind it is the
//      540 × 540 thumbnail, not the 1000 × 700 original.
//   3. Switch to session B and back. The bubble's <img> has the same URL.

import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'
import { makePng } from '../../helpers/png.js'

const SID_A = 'ses_e2etab0a'
const SID_B = 'ses_e2etab0b'
const WIDTH = 1000
const HEIGHT = 700
const THUMBNAIL_SIDE = 540

const BAR_IMAGE = '[data-testid=attachments-bar] img.attach-thumb'
const BUBBLE_IMAGE = '[data-testid=attachments] img.msg-image'

test.describe('regression: attached-image-url', () => {
  test('the bar and the bubble show one thumbnail URL, kept across a tab switch', async ({ page, request }) => {
    await seedSession(request, 'e2e-tab-a')
    await seedSession(request, 'e2e-tab-b')
    await openClient(page, { sid: SID_A })

    // (1) Pick the image through the ⋯ menu's file chooser.
    const png = makePng(WIDTH, HEIGHT, (x, y) => [x % 256, y % 256, (x + y) % 256])
    const chooser = page.waitForEvent('filechooser')
    await page.locator('[data-testid=more-menu-toggle]').click()
    await page.locator('[data-testid=more-menu-file-attach]').click()
    await (await chooser).setFiles({ name: 'big.png', mimeType: 'image/png', buffer: png })
    const bar = page.locator(BAR_IMAGE)
    await expect(bar).toBeVisible({ timeout: 8_000 })
    const barUrl = await bar.getAttribute('src')
    expect(barUrl).toMatch(/^blob:/)

    // (2) Send it: the bubble shows the same URL, and the picture behind it is the thumbnail.
    await page.locator('[data-testid=chat-input]').fill('an image')
    await page.locator('[data-testid=chat-send-button]').click()
    const bubble = page.locator(BUBBLE_IMAGE)
    await expect(bubble).toHaveCount(1, { timeout: 10_000 })
    await expect(bubble).toHaveAttribute('src', barUrl)
    await expect(bubble).toHaveJSProperty('naturalWidth', THUMBNAIL_SIDE)
    await expect(bubble).toHaveJSProperty('naturalHeight', THUMBNAIL_SIDE)

    // (3) Switch to B and back: the bubble mounts again and shows the same URL.
    await page.locator('[data-testid=drawer-toggle]').click()
    await page.locator(`[data-testid=session-list-item][data-cpc-sid="${SID_B}"] [data-testid=session-list-item-select]`).click()
    await expect(page.locator(BUBBLE_IMAGE)).toHaveCount(0)
    await page.locator('[data-testid=drawer-toggle]').click()
    await page.locator(`[data-testid=session-list-item][data-cpc-sid="${SID_A}"] [data-testid=session-list-item-select]`).click()
    await expect(page.locator(BUBBLE_IMAGE)).toHaveCount(1)
    await expect(page.locator(BUBBLE_IMAGE)).toHaveAttribute('src', barUrl)
  })
})
