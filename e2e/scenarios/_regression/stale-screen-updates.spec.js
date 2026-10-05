// Regression: a screen that was left open kept running the build it was opened with.
// A new build only reached it on the next cold start, or when "Update app" was pressed.

import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'
import { redeploy, restoreDeploy } from '../../helpers/redeploy.js'

const SID = 'ses_e2echatgld'

// The build a screen is running, read off the entry script it loaded
// (null while the page is in the middle of loading again).
function runningBuild(page) {
  return page.evaluate(() => {
    const entry = document.querySelector('script[type=module][src*="/assets/index-"]')
    return entry ? entry.getAttribute('src') : null
  }).catch(() => null)
}

// The app goes to the background and comes back (what switching apps on a phone does).
async function backgroundAndReturn(page) {
  for (const state of ['hidden', 'visible']) {
    await page.evaluate((v) => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => v })
      document.dispatchEvent(new Event('visibilitychange'))
    }, state)
    await page.waitForTimeout(300)
  }
}

async function waitForServiceWorker(page) {
  await page.evaluate(() => navigator.serviceWorker.ready.then(() => true))
  await expect.poll(() => page.evaluate(() => !!navigator.serviceWorker.controller)).toBe(true)
}

test.describe('regression: an open screen moves to a newly deployed build', () => {
  test.afterEach(() => restoreDeploy())

  test('coming back to the foreground picks up the new build and keeps the half-typed message', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })
    await waitForServiceWorker(page)
    const before = await runningBuild(page)
    expect(before).toBeTruthy()

    await page.locator('[data-testid=chat-input]').fill('half-typed, not sent yet')
    redeploy('r2')
    // Nothing navigates: the screen is simply left open, goes to the background, comes back.
    await backgroundAndReturn(page)

    await expect.poll(() => runningBuild(page), { timeout: 20_000 }).toContain('_r2')
    await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible' })
    await expect(page.locator('[data-testid=chat-input]')).toHaveValue('half-typed, not sent yet')
  })

  test('a part loaded on demand still opens on a screen one build behind', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })
    await waitForServiceWorker(page)
    const before = await runningBuild(page)

    // A deploy keeps the files of the build it replaces, so the drawer (not loaded
    // yet on this screen) can still be fetched under its old name.
    redeploy('r2')
    await page.locator('.hamburger').click()
    await expect(page.locator('.drawer-global-menu')).toBeVisible({ timeout: 10_000 })
    expect(await runningBuild(page)).toBe(before)
  })

  test('when the files of its build are gone, the screen moves itself to the new build', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })
    await waitForServiceWorker(page)

    // Two deploys later the old files no longer exist: opening the drawer fails to
    // load, and the screen answers by refreshing itself onto the current build.
    redeploy('r3', { keepOld: false })
    await page.locator('.hamburger').click()
    await expect.poll(() => runningBuild(page), { timeout: 30_000 }).toContain('_r3')

    // On the new build the same press works.
    await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible' })
    await page.locator('.hamburger').click()
    await expect(page.locator('.drawer-global-menu')).toBeVisible({ timeout: 10_000 })
  })

  test('the menu shows which build the screen is running', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })
    const entry = await runningBuild(page)
    const id = /index-(.+)\.js$/.exec(entry)[1]

    await page.locator('.hamburger').click()
    await page.locator('.drawer-global-menu').click()
    await expect(page.locator('[data-testid=running-build]')).toHaveText(`build ${id}`)
  })
})
