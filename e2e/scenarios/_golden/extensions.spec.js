// Golden path: extensions.
// The e2e config declares one extension (`fixture`), and the test backend serves
// it at /ext/fixture/ (= backend/routes/debug_e2e.py). The page prints its own
// load time, so matching values before and after collapsing prove the iframe
// document survived (= collapsing must not stop an extension's audio).

import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'

test.describe('golden: extensions', () => {
  test('toggle opens the band, and collapsing keeps the iframe alive', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })

    // One 🧩 slot in the top bar; the extension is picked from its list.
    const slot = page.locator('[data-testid=extension-menu-toggle]')
    await expect(slot).toBeVisible({ timeout: 10_000 })
    await expect(slot).toHaveText('🧩')
    const toggle = async () => {
      await slot.click()
      await page.locator('[data-testid=extension-item-fixture]').click()
    }
    await expect(page.locator('[data-testid=extension-item-fixture]')).toHaveCount(0)

    await toggle()
    const band = page.locator('[data-testid=extension-band]')
    await expect(band).toBeVisible()
    const born = page.frameLocator('[data-testid=extension-iframe-fixture]').locator('#born')
    await expect(born).not.toHaveText('')
    const bornAt = await born.textContent()

    // Collapse: the band has no height, but the iframe document stays.
    await toggle()
    await expect(page.locator('[data-testid=extension-band]')).toHaveClass(/collapsed/)
    await expect(page.locator('[data-testid=extension-iframe-fixture]')).toHaveCount(1)

    // The chat input stays usable while the extension is open.
    await toggle()
    await expect(page.locator('[data-testid=chat-input]')).toBeVisible()
    await expect(born).toHaveText(bornAt)
  })

  test('opening screenshare collapses the extension band', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await page.evaluate(() => localStorage.setItem('cpc_e2e_moonlight', '1'))
    await openClient(page, { sid: SID })

    await page.locator('[data-testid=extension-menu-toggle]').click()
    await page.locator('[data-testid=extension-item-fixture]').click()
    await expect(page.locator('[data-testid=extension-band]')).not.toHaveClass(/collapsed/)
    await page.locator('[data-testid=screenshare-toggle]').click()
    await expect(page.locator('[data-testid=extension-band]')).toHaveClass(/collapsed/)
  })

  test('dragging the bottom handle resizes the band and the height survives a reload', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })
    await page.evaluate(() => localStorage.removeItem('cpc.extensions.bandPct'))

    const open = async () => {
      await page.locator('[data-testid=extension-menu-toggle]').click()
      await page.locator('[data-testid=extension-item-fixture]').click()
    }
    await open()
    const band = page.locator('[data-testid=extension-band]')
    const viewport = page.viewportSize()
    const before = (await band.boundingBox()).height
    // Default is 30% of the screen.
    expect(Math.abs(before - viewport.height * 0.3)).toBeLessThan(4)

    // Drag the handle down by 10% of the screen.
    const handle = (await page.locator('[data-testid=extension-resize]').boundingBox())
    const x = handle.x + handle.width / 2
    const y = handle.y + handle.height / 2
    await page.mouse.move(x, y)
    await page.mouse.down()
    await page.mouse.move(x, y + viewport.height * 0.1, { steps: 5 })
    await page.mouse.up()
    const after = (await band.boundingBox()).height
    expect(Math.abs(after - viewport.height * 0.4)).toBeLessThan(4)

    // The height is kept per device.
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible' })
    await open()
    const reloaded = (await page.locator('[data-testid=extension-band]').boundingBox()).height
    expect(Math.abs(reloaded - after)).toBeLessThan(4)
  })
})
