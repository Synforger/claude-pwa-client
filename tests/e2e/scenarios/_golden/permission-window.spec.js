// Golden path: permission-window feature.
// A permission window of Claude Code is put into the tab's status through /debug/e2e/inject-pending-permission (the
// status stream carries it on its next tick, as it carries a pending plan). The 🔐 button then stands in the topbar;
// it opens the whole input, "Allow" sends the window's number to the answer door, and a queue shows "k / N". The
// answer door is answered by the scenario (the test backend has no Claude Code to type into), so what is checked is
// what the screen sends and how it ends the dialog.
//
// With CPC_E2E_SHOT_DIR set, the 390 px pictures of the dialog (a 1500-character command, and a rewritten input) are
// written there.

import { test, expect } from '@playwright/test'
import { join } from 'node:path'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

// With the service worker running, the answer this scenario gives the answer door (`page.route`) did not reach the
// screen in WebKit: the real backend answered instead. Chromium got it either way; both projects run the same way.
test.use({ serviceWorkers: 'block' })

const SID = 'ses_e2echatgld'
const ANSWER_URL = `**/pty/${SID}/permission/answer`
const LONG_COMMAND = `echo ${'0123456789'.repeat(150)} && ls -la`
const PHONE = { width: 390, height: 844 }

const openButton = page => page.locator('[data-testid=permission-window-open-button]')
const dialog = page => page.locator('[data-testid=permission-window-dialog]')

async function inject(request, window) {
  const res = await request.post(`/debug/e2e/inject-pending-permission/${SID}`, { data: window })
  expect(res.status()).toBe(200)
}

async function shoot(page, name) {
  if (process.env.CPC_E2E_SHOT_DIR) await page.screenshot({ path: join(process.env.CPC_E2E_SHOT_DIR, name) })
}

test.describe('golden: permission-window', () => {
  test.beforeEach(async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })
  })

  test.afterEach(async ({ request }) => {
    await seedSession(request, 'e2e-chat-golden')   // seeding the tab again closes its window for the next scenario
  })

  test('no window, no button', async ({ page }) => {
    await expect(openButton(page)).toHaveCount(0)
  })

  test('opens the whole command, and Allow sends the window\'s number to the answer door', async ({ page, request }) => {
    const answers = []
    await page.route(ANSWER_URL, async route => {
      answers.push(route.request().postDataJSON())
      await route.fulfill({ json: { ok: true } })
    })
    await inject(request, { number: 7, tool_name: 'Bash', input: { command: LONG_COMMAND }, index: 1, count: 1 })

    await expect(openButton(page)).toBeVisible({ timeout: 15_000 })
    await openButton(page).click()
    await expect(dialog(page)).toBeVisible()
    await expect(page.locator('[data-testid=permission-window-running] pre')).toHaveText(LONG_COMMAND)
    await expect(page.locator('[data-testid=permission-window-position]')).toHaveCount(0)
    await expect(page.locator('[data-testid=permission-window-rewritten]')).toHaveCount(0)

    await page.locator('[data-testid=permission-window-answer][data-cpc-answer=allow]').click()
    await expect(dialog(page)).toHaveCount(0)
    expect(answers).toEqual([{ number: 7, answer: 'allow' }])
    // The window is still in the status (nothing typed into a real Claude Code), so its button stays
    await expect(openButton(page)).toBeVisible()
  })

  test('Deny sends deny; a stale number ends the dialog quietly and the button stays', async ({ page, request }) => {
    const answers = []
    await page.route(ANSWER_URL, async route => {
      answers.push(route.request().postDataJSON())
      await route.fulfill({ status: 409, json: { detail: { code: 'permission_stale' } } })
    })
    await inject(request, { number: 2, input: { command: 'ls' } })
    await expect(openButton(page)).toBeVisible({ timeout: 15_000 })
    await openButton(page).click()
    await page.locator('[data-testid=permission-window-answer][data-cpc-answer=deny]').click()
    await expect(dialog(page)).toHaveCount(0)
    expect(answers).toEqual([{ number: 2, answer: 'deny' }])
    await expect(openButton(page)).toBeVisible()
  })

  test('an answer that could not be sent keeps the dialog open with one line and live buttons', async ({ page, request }) => {
    await page.route(ANSWER_URL, route => route.fulfill({ status: 500, json: { detail: 'boom' } }))
    await inject(request, { number: 3, input: { command: 'ls' } })
    await expect(openButton(page)).toBeVisible({ timeout: 15_000 })
    await openButton(page).click()
    await page.locator('[data-testid=permission-window-answer][data-cpc-answer=allow]').click()
    await expect(page.locator('[data-testid=permission-window-failed]')).toBeVisible()
    await expect(dialog(page)).toBeVisible()
    await expect(page.locator('[data-testid=permission-window-answer][data-cpc-answer=allow]')).toBeEnabled()
  })

  test('a queue shows "k / N", and a newer window replaces the one on screen', async ({ page, request }) => {
    await inject(request, { number: 4, input: { command: 'first' }, index: 2, count: 3 })
    await expect(openButton(page)).toBeVisible({ timeout: 15_000 })
    await openButton(page).click()
    await expect(page.locator('[data-testid=permission-window-position]')).toHaveText('2 / 3')

    await inject(request, { number: 5, input: { command: 'second' }, index: 3, count: 3 })
    await expect(page.locator('[data-testid=permission-window-position]')).toHaveText('3 / 3')
    await expect(page.locator('[data-testid=permission-window-running] pre')).toHaveText('second')
  })

  test('a rewritten input shows both inputs and the guard\'s line', async ({ page, request }) => {
    await inject(request, {
      number: 6,
      input: { command: 'ls -la' },
      record_input: { command: 'rm -rf build', description: 'Clean the build' },
    })
    await expect(openButton(page)).toBeVisible({ timeout: 15_000 })
    await openButton(page).click()
    await expect(page.locator('[data-testid=permission-window-rewritten]')).toBeVisible()
    await expect(page.locator('[data-testid=permission-window-running]')).toContainText('ls -la')
    await expect(page.locator('[data-testid=permission-window-original]')).toContainText('rm -rf build')
    await expect(page.locator('[data-testid=permission-window-original]')).toContainText('Clean the build')
  })

  test('the tab\'s row in the list is marked while its window is open', async ({ page, request }) => {
    await inject(request, { number: 8, input: { command: 'ls' } })
    await expect(openButton(page)).toBeVisible({ timeout: 15_000 })
    // The detector looks at the pane about once a second, and its look must not take the injected window away
    await page.waitForTimeout(3000)
    await expect(openButton(page)).toBeVisible()
    await page.locator('[data-testid=drawer-toggle]').click()
    await expect(page.locator('[data-testid=session-drawer]')).toBeVisible()
    await expect(page.locator(`[data-testid=session-list-item][data-cpc-sid="${SID}"] [data-testid=session-permission-window]`)).toBeVisible()
  })

  test('on a phone: a 1500-character command, and a rewritten input, stay inside the screen', async ({ page, request }) => {
    await page.setViewportSize(PHONE)
    const longInput = { command: `echo ${'abcdefghij'.repeat(150)}` }
    await inject(request, { number: 9, input: longInput })
    await expect(openButton(page)).toBeVisible({ timeout: 15_000 })
    await openButton(page).click()
    await expect(dialog(page)).toBeVisible()
    const box = await page.locator('.permission-window-dialog').boundingBox()
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(PHONE.width)
    const wraps = await page.locator('[data-testid=permission-window-running] pre').evaluate(el => el.scrollWidth <= el.clientWidth)
    expect(wraps).toBe(true)
    await shoot(page, 'permission-window-long-command-390.png')

    await page.locator('.permission-window-close').click()
    await inject(request, {
      number: 10,
      input: { command: 'ls -la build' },
      record_input: { command: 'rm -rf build && echo done', description: 'Clean the build folder before the run' },
      index: 1,
      count: 2,
    })
    await openButton(page).click()
    await expect(page.locator('[data-testid=permission-window-rewritten]')).toBeVisible()
    await shoot(page, 'permission-window-rewritten-390.png')
  })
})
