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

    // One 🧩 slot in the top bar; a tap opens / collapses the last used
    // extension (the only one here), without going through the list.
    const slot = page.locator('[data-testid=extension-menu-toggle]')
    await expect(slot).toBeVisible({ timeout: 10_000 })
    await expect(slot).toHaveText('🧩')
    const toggle = async () => { await slot.click() }

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

    // ✕ in the band's corner collapses it too, and the document still survives.
    await page.locator('[data-testid=extension-close]').click()
    await expect(page.locator('[data-testid=extension-band]')).toHaveClass(/collapsed/)
    await expect(page.locator('[data-testid=extension-iframe-fixture]')).toHaveCount(1)
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
    await expect(page.locator('[data-testid=extension-band]')).not.toHaveClass(/collapsed/)
    await page.locator('[data-testid=screenshare-toggle]').click()
    await expect(page.locator('[data-testid=extension-band]')).toHaveClass(/collapsed/)
  })

  test('dragging the bottom handle resizes the band and the height survives a reload', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })
    await page.evaluate(() => localStorage.removeItem('cpc.extensions.bandPct'))

    const open = async () => { await page.locator('[data-testid=extension-menu-toggle]').click() }
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

  test('a long press or a right click lists the extensions; a tap does not', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })
    const slot = page.locator('[data-testid=extension-menu-toggle]')
    const item = page.locator('[data-testid=extension-item-fixture]')
    await expect(slot).toBeVisible({ timeout: 10_000 })

    // Tap: the band opens directly, no list.
    await slot.click()
    await expect(page.locator('[data-testid=extension-band]')).not.toHaveClass(/collapsed/)
    await expect(item).toHaveCount(0)
    await slot.click()
    await expect(page.locator('[data-testid=extension-band]')).toHaveClass(/collapsed/)

    // Long press: the list opens and the band stays collapsed.
    const box = await slot.boundingBox()
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.down()
    await page.waitForTimeout(800)
    await page.mouse.up()
    await expect(item).toBeVisible()
    await expect(page.locator('[data-testid=extension-band]')).toHaveClass(/collapsed/)
    // Picking from the list opens it.
    await item.click()
    await expect(page.locator('[data-testid=extension-band]')).not.toHaveClass(/collapsed/)
    await expect(item).toHaveCount(0)

    // Right click (desktop) also lists.
    await slot.click({ button: 'right' })
    await expect(item).toBeVisible()
  })

  test('an extension declared as a page fills the space above the chat input, with no height to set', async ({ page, request }, testInfo) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })
    const slot = page.locator('[data-testid=extension-menu-toggle]')
    await expect(slot).toBeVisible({ timeout: 10_000 })
    const band = page.locator('[data-testid=extension-band]')
    const messages = page.locator('.messages')
    const input = page.locator('[data-testid=chat-input]')
    await expect(messages).toBeVisible()

    // Pick the page extension from the list.
    await slot.click({ button: 'right' })
    await page.locator('[data-testid=extension-item-fixture-page]').click()
    await expect(band).toHaveClass(/page/)
    await expect(page.frameLocator('[data-testid=extension-iframe-fixture-page]').locator('#born')).not.toHaveText('')

    // It takes the place of the message list: from under the top bar down to the chat input.
    await expect(messages).toBeHidden()
    await expect(input).toBeVisible()
    const viewport = page.viewportSize()
    const frame = await band.boundingBox()
    const bar = await page.locator('header.topbar').boundingBox()
    const typing = await input.boundingBox()
    expect(Math.abs(frame.y - (bar.y + bar.height))).toBeLessThan(2)
    expect(frame.y + frame.height).toBeLessThanOrEqual(typing.y + 1)
    expect(frame.height).toBeGreaterThan(viewport.height * 0.5)
    // A page has no height to set: no resize handle, no fullscreen button.
    await expect(page.locator('[data-testid=extension-resize]')).toHaveCount(0)
    await expect(page.locator('.extension-ctrl-full')).toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath('extension-page.png') })

    // The chat input keeps working while the page is open.
    await input.fill('a note while reading')
    await page.locator('[data-testid=chat-send-button]').click()

    // ✕ gives the place back to the conversation, with what was sent meanwhile in it.
    await page.locator('[data-testid=extension-close]').click()
    await expect(band).toHaveClass(/collapsed/)
    await expect(messages).toBeVisible()
    await expect(page.locator('[data-testid=message-bubble-user]').filter({ hasText: 'a note while reading' }))
      .toHaveCount(1, { timeout: 20_000 })

    // An extension with no `view` opened after it is a band again, beside the conversation.
    await slot.click({ button: 'right' })
    await page.locator('[data-testid=extension-item-fixture]').click()
    await expect(band).not.toHaveClass(/collapsed/)
    await expect(band).not.toHaveClass(/page/)
    await expect(messages).toBeVisible()
    await expect(page.locator('[data-testid=extension-resize]')).toHaveCount(1)
    expect((await band.boundingBox()).height).toBeLessThan(viewport.height * 0.75)
  })
})
