// Golden path: the tab list kept on the left of a wide screen with a mouse (chromium-desktop, 1280x800).
// It starts open and pushes everything under the status bar to the right by its width, a tab chosen or made does not
// shut it, ☰ and its ✕ shut it and the machine remembers, a window that turns narrow shuts it without writing, and the
// terminal still fits the width that is left. The phone (webkit-mobile) keeps the list laid over the screen with a curtain.
// Pictures of each state go to the test's output folder (`test-results/<test>/`).

import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { DRAWER_DOCKED_KEY, openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'
const DOCKED_WIDTH_PX = 320
const WIDE = { width: 1280, height: 800 }
const NARROW = { width: 800, height: 800 }
// A fractional zoom or a 1px border can move an edge by one pixel.
const EDGE_TOLERANCE_PX = 1.5

const DESKTOP_ONLY = 'the list is kept on the left only on a wide screen with a mouse'

async function box(locator) {
  const found = await locator.boundingBox()
  expect(found, 'the element has a box').not.toBeNull()
  return found
}

const remembered = (page) => page.evaluate((key) => window.localStorage.getItem(key), DRAWER_DOCKED_KEY)

async function shoot(page, testInfo, name) {
  await page.screenshot({ path: testInfo.outputPath(`${name}.png`) })
}

test.describe('golden: docked tab list', () => {
  test.beforeEach(async ({ request }) => {
    await seedSession(request, 'e2e-chat-golden')
  })

  test('starts open, and the body starts where the list ends while the status bar stays full width', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'chromium-desktop', DESKTOP_ONLY)
    await openClient(page, { sid: SID, docked: true })

    const drawer = page.locator('[data-testid=session-drawer]')
    await expect(drawer).toBeVisible()
    await expect(page.locator('.drawer-overlay')).toHaveCount(0)

    const bar = await box(page.locator('[data-testid=status-bar]'))
    const list = await box(drawer)
    const topbar = await box(page.locator('header.topbar'))
    const input = await box(page.locator('[data-testid=chat-input]'))

    // The bar is as wide as the window and starts at its left edge; the list starts under it and runs to the window's bottom.
    expect(bar.x).toBeCloseTo(0, 0)
    expect(bar.width).toBeCloseTo(WIDE.width, 0)
    expect(Math.abs(list.y - (bar.y + bar.height))).toBeLessThanOrEqual(EDGE_TOLERANCE_PX)
    expect(Math.abs(list.y + list.height - WIDE.height)).toBeLessThanOrEqual(EDGE_TOLERANCE_PX)
    expect(Math.abs(list.width - DOCKED_WIDTH_PX)).toBeLessThanOrEqual(EDGE_TOLERANCE_PX)

    // The body (top bar, chat input) starts at the list's right edge, never under it.
    expect(topbar.x).toBeGreaterThanOrEqual(list.x + list.width - EDGE_TOLERANCE_PX)
    expect(Math.abs(topbar.x - DOCKED_WIDTH_PX)).toBeLessThanOrEqual(EDGE_TOLERANCE_PX)
    expect(input.x).toBeGreaterThanOrEqual(list.x + list.width - EDGE_TOLERANCE_PX)
    expect(Math.abs(topbar.x + topbar.width - WIDE.width)).toBeLessThanOrEqual(EDGE_TOLERANCE_PX)

    await shoot(page, testInfo, 'desktop-open')
  })

  test('stays open after a tab is chosen and after a tab is made', async ({ page, request }, testInfo) => {
    test.skip(testInfo.project.name !== 'chromium-desktop', DESKTOP_ONLY)
    await openClient(page, { sid: SID, docked: true })
    const drawer = page.locator('[data-testid=session-drawer]')
    await expect(drawer).toBeVisible()

    await page.locator('[data-testid=session-list-item-select]').first().click()
    await expect(drawer).toBeVisible()

    const countSessions = async () => {
      const body = await (await request.get('/sessions')).json()
      return (body.sessions || body).length
    }
    const before = await countSessions()
    await page.locator('[data-testid=new-session-button]').click()
    await page.locator('.agent-picker .agent-picker-item').first().click()
    await expect(page.locator('.agent-picker-label')).toHaveText('Pick an account:')
    await page.locator('.agent-picker .agent-picker-item').first().click()
    await expect.poll(countSessions, { timeout: 10_000 }).toBe(before + 1)
    await expect(drawer).toBeVisible()
    expect((await box(page.locator('header.topbar'))).x).toBeGreaterThanOrEqual(DOCKED_WIDTH_PX - EDGE_TOLERANCE_PX)

    await shoot(page, testInfo, 'desktop-after-new-tab')
  })

  test('☰ and ✕ shut it, ☰ opens it, and the machine remembers each over a reload', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'chromium-desktop', DESKTOP_ONLY)
    await openClient(page, { sid: SID, docked: true })
    const drawer = page.locator('[data-testid=session-drawer]')
    const toggle = page.locator('[data-testid=drawer-toggle]')
    await expect(drawer).toBeVisible()
    expect(await remembered(page)).toBeNull()

    await toggle.click()
    await expect(drawer).toHaveCount(0)
    expect(await remembered(page)).toBe('false')
    // Shut: the body takes the whole width again.
    expect(Math.abs((await box(page.locator('header.topbar'))).x)).toBeLessThanOrEqual(EDGE_TOLERANCE_PX)
    await shoot(page, testInfo, 'desktop-shut')

    await page.reload()
    await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible', timeout: 15_000 })
    await expect(drawer).toHaveCount(0)

    await toggle.click()
    await expect(drawer).toBeVisible()
    expect(await remembered(page)).toBe('true')
    await page.reload()
    await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible', timeout: 15_000 })
    await expect(drawer).toBeVisible()

    await page.locator('[data-testid=drawer-close]').click()
    await expect(drawer).toHaveCount(0)
    expect(await remembered(page)).toBe('false')
  })

  test('shuts when the window turns narrow, opens again when it turns wide, and writes nothing meanwhile', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'chromium-desktop', DESKTOP_ONLY)
    await openClient(page, { sid: SID, docked: true })
    const drawer = page.locator('[data-testid=session-drawer]')
    await expect(drawer).toBeVisible()

    await page.setViewportSize(NARROW)
    await expect(drawer).toHaveCount(0)
    expect(await remembered(page)).toBeNull()
    expect(Math.abs((await box(page.locator('header.topbar'))).x)).toBeLessThanOrEqual(EDGE_TOLERANCE_PX)
    await shoot(page, testInfo, 'desktop-narrow-window')

    await page.setViewportSize(WIDE)
    await expect(drawer).toBeVisible()
    expect(await remembered(page)).toBeNull()
  })

  test('the terminal fits the width that is left of the list', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'chromium-desktop', DESKTOP_ONLY)
    await openClient(page, { sid: SID, docked: true })
    const drawer = page.locator('[data-testid=session-drawer]')
    await expect(drawer).toBeVisible()

    await page.locator('[data-testid=more-menu-toggle]').click()
    await page.locator('[data-testid=view-toggle]').click()
    const pane = page.locator('[data-testid=terminal-pane]')
    await expect(pane).toBeVisible({ timeout: 10_000 })
    await page.waitForFunction(() => !!window.__cpcTerm?.snapshot, null, { timeout: 5_000 })

    const list = await box(drawer)
    const paneBox = await box(pane)
    const screen = await box(page.locator('.xterm-screen'))
    expect(paneBox.x).toBeGreaterThanOrEqual(list.x + list.width - EDGE_TOLERANCE_PX)
    // The rows of text stay inside the pane (not under the list, not past the window), and what the columns leave over is
    // less than a few cells: the width was measured after the body moved.
    expect(screen.x).toBeGreaterThanOrEqual(list.x + list.width - EDGE_TOLERANCE_PX)
    expect(screen.x + screen.width).toBeLessThanOrEqual(paneBox.x + paneBox.width + EDGE_TOLERANCE_PX)
    expect(paneBox.x + paneBox.width - (screen.x + screen.width)).toBeLessThan(40)
    await shoot(page, testInfo, 'desktop-terminal')

    // Shut the list: the terminal takes the width back.
    await page.locator('[data-testid=drawer-toggle]').click()
    await expect(drawer).toHaveCount(0)
    await expect.poll(async () => (await box(page.locator('.xterm-screen'))).width).toBeGreaterThan(screen.width + DOCKED_WIDTH_PX - 40)
    await shoot(page, testInfo, 'desktop-terminal-list-shut')
  })

  test('on a phone the list stays laid over the screen: shut at the start, a curtain, shut after a tab is chosen', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'webkit-mobile', 'the phone project')
    await openClient(page, { sid: SID, docked: true })
    const drawer = page.locator('[data-testid=session-drawer]')
    await expect(drawer).toHaveCount(0)
    expect(Math.abs((await box(page.locator('header.topbar'))).x)).toBeLessThanOrEqual(EDGE_TOLERANCE_PX)
    await shoot(page, testInfo, 'phone-start')

    await page.locator('[data-testid=drawer-toggle]').click()
    await expect(drawer).toBeVisible()
    await expect(page.locator('.drawer-overlay')).toBeVisible()
    // The body did not move: the list covers it.
    expect(Math.abs((await box(page.locator('header.topbar'))).x)).toBeLessThanOrEqual(EDGE_TOLERANCE_PX)
    await shoot(page, testInfo, 'phone-open')

    await page.locator('[data-testid=session-list-item-select]').first().click()
    await expect(drawer).toHaveCount(0)
    expect(await remembered(page)).toBeNull()
  })
})
