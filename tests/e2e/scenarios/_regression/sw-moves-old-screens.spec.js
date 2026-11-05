// Regression: a screen of an old build kept running after a deploy. It has no check of its own (the code that moves a
// screen to a new build did not exist yet), so only the service worker can move it: when a new worker takes over, it
// reloads the screens that did not announce themselves, and leaves the ones that did (they move themselves, and hold
// their own reload while an attachment is picked but not sent).

import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'
import { redeploy, restoreDeploy } from '../../helpers/redeploy.js'

const SID = 'ses_e2echatgld'
const BACKEND_LOG = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', 'fixtures', '_runtime', 'logs', 'backend.error.log')

// 1x1 transparent PNG.
const TINY_PNG_B64 =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4XmNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg=='

const runningBuild = (page) => page.evaluate(() => {
  const entry = document.querySelector('script[type=module][src*="/assets/index-"]')
  return entry ? entry.getAttribute('src') : null
}).catch(() => null)

async function waitForServiceWorker(page) {
  await page.evaluate(() => navigator.serviceWorker.ready.then(() => true))
  await expect.poll(() => page.evaluate(() => !!navigator.serviceWorker.controller)).toBe(true)
}

// Asks the registration to look for a new worker, as the browser does when a screen is brought back. Nothing else
// is done to the screen: whatever moves it is the worker.
const lookForNewWorker = (page) => page.evaluate(() => navigator.serviceWorker.getRegistration().then(reg => reg.update()))

const swNavigateRecords = () => readFileSync(BACKEND_LOG, 'utf-8').split('\n').filter(line => line.includes('"stage": "update:sw-navigate"'))

// Makes the screen what a screen of an old build is: it does not announce itself to the worker, and it does not move
// itself when a new worker takes over.
async function makeScreenOld(page) {
  await page.addInitScript(() => {
    const drop = EventTarget.prototype.addEventListener
    ServiceWorkerContainer.prototype.addEventListener = function (type, ...rest) {
      if (type === 'controllerchange') return undefined
      return drop.call(this, type, ...rest)
    }
    const post = ServiceWorker.prototype.postMessage
    ServiceWorker.prototype.postMessage = function (message, ...rest) {
      if (message && message.type === 'self-updating') return undefined
      return post.call(this, message, ...rest)
    }
  })
}

test.describe('regression: the service worker moves the screens that cannot move themselves', () => {
  test.afterEach(() => restoreDeploy())

  test('a screen that does not announce itself is reloaded onto the new build, and the move is recorded', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await makeScreenOld(page)
    await openClient(page, { sid: SID })
    await waitForServiceWorker(page)
    const before = await runningBuild(page)
    await page.evaluate(() => { window.__stillTheOldPage = true })
    const recordedBefore = swNavigateRecords().length

    redeploy('r2')
    await lookForNewWorker(page)

    await expect.poll(() => runningBuild(page), { timeout: 30_000 }).toContain('_r2')
    expect(await runningBuild(page)).not.toBe(before)
    await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible' })
    expect(await page.evaluate(() => window.__stillTheOldPage)).toBeUndefined()
    await expect.poll(() => swNavigateRecords().length, { timeout: 10_000 }).toBe(recordedBefore + 1)
    expect(swNavigateRecords().at(-1)).toContain('"moved": ["/"]')
  })

  test('a screen that announced itself is left to move itself, and keeps an attachment that is not sent', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })
    await waitForServiceWorker(page)
    const before = await runningBuild(page)

    const chooser = page.waitForEvent('filechooser')
    await page.locator('[data-testid=more-menu-toggle]').click()
    await page.locator('[data-testid=more-menu-file-attach]').click()
    await (await chooser).setFiles({ name: 'tiny.png', mimeType: 'image/png', buffer: Buffer.from(TINY_PNG_B64, 'base64') })
    await expect(page.locator('[data-testid=attachments-bar]')).toBeVisible()
    const recordedBefore = swNavigateRecords().length

    redeploy('r2')
    await lookForNewWorker(page)

    // Well past the time the worker waits for announcements: the screen is the same page with its file.
    await page.waitForTimeout(6000)
    expect(await runningBuild(page)).toBe(before)
    await expect(page.locator('[data-testid=attachments-bar]')).toBeVisible()
    expect(swNavigateRecords().length).toBe(recordedBefore)

    // It still moves itself once the file is gone.
    await page.locator('.attach-remove').click()
    await expect.poll(() => runningBuild(page), { timeout: 20_000 }).toContain('_r2')
  })

  test('the first worker of a screen reloads nothing', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    const recordedBefore = swNavigateRecords().length
    await makeScreenOld(page)
    await openClient(page, { sid: SID })
    await waitForServiceWorker(page)
    await page.evaluate(() => { window.__stillTheOldPage = true })
    await page.waitForTimeout(6000)
    expect(await page.evaluate(() => window.__stillTheOldPage)).toBe(true)
    expect(swNavigateRecords().length).toBe(recordedBefore)
  })
})
