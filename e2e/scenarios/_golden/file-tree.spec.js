// Golden path: file-tree feature.
// The status bar ⋯ menu has a file-tree entry that mounts the tree modal, and the
// favorites it stars are one list kept on the host.

import { appendFileSync, mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'

test.describe('golden: file-tree', () => {
  test('tree modal opens through the ⋯ menu', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })

    await page.locator('[data-testid=more-menu-toggle]').click()
    await page.locator('[data-testid=more-menu-file-tree]').click()
    await expect(page.locator('[data-testid=file-tree-modal]')).toBeVisible({ timeout: 5_000 })
  })
})

// The favorites list lives on the host: one path per line in the user's favorites.txt.
test.describe('golden: favorites', () => {
  const FAVORITES_FILE = resolve(
    dirname(fileURLToPath(import.meta.url)), '..', '..', 'fixtures', '_runtime', 'user', 'favorites.txt',
  )
  const DIR = `${process.env.HOME}/cpc-e2e-favorites` // never created: a favorite may name a missing path
  const rows = (page) => page.locator('.tree-fav-entry')
  const hostList = async (request) => (await (await request.get('/favorites')).json()).favorites.map((f) => f.path)
  const clearFavorites = async (request) => {
    for (const path of await hostList(request)) await request.delete('/favorites', { params: { path } })
  }
  const openPicker = (page) => page.locator('[data-testid=favorites-open-button]').click()
  const closePicker = (page) => page.locator('.tree-overlay .modal-close').click()

  test.beforeEach(async ({ request }) => { await clearFavorites(request) })
  test.afterEach(async ({ request }) => { await clearFavorites(request) })

  test('the star in the preview changes the list on the host, and it survives the browser clearing its storage', async ({ page, request }) => {
    const path = `${DIR}/one.md`
    await request.post('/favorites', { data: { path } })
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })

    await openPicker(page)
    await expect(rows(page)).toHaveCount(1)
    await expect(rows(page)).toContainText('one.md')
    await rows(page).locator('.tree-fav-main').click()

    const star = page.locator('[data-testid=file-preview-modal] .modal-fav-btn')
    await expect(star).toHaveText('★')
    await star.click()
    await expect(star).toHaveText('☆')
    await expect.poll(() => hostList(request)).toEqual([])
    await star.click()
    await expect(star).toHaveText('★')
    await expect.poll(() => hostList(request)).toEqual([path])

    // Nothing of the list is kept in this browser.
    await page.evaluate(() => { localStorage.clear(); sessionStorage.clear() })
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible' })
    await openPicker(page)
    await expect(rows(page)).toHaveCount(1)
    await expect(rows(page)).toContainText('one.md')
  })

  test('the list a browser used to keep is carried over to the host once', async ({ page, request }) => {
    const path = `${DIR}/kept-on-device.md`
    // Seed the old storage key before the app loads, on the first load only.
    await page.addInitScript(([key, value]) => {
      if (sessionStorage.getItem('cpc-e2e-seeded')) return
      sessionStorage.setItem('cpc-e2e-seeded', '1')
      localStorage.setItem(key, value)
    }, ['cpc.fileTree.favorites', JSON.stringify([{ path, name: 'kept-on-device.md', is_dir: false }])])
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })

    await expect.poll(() => hostList(request)).toEqual([path])
    expect(await page.evaluate(() => localStorage.getItem('cpc.fileTree.favorites'))).toBeNull()
    await openPicker(page)
    await expect(rows(page)).toContainText('kept-on-device.md')
  })

  test('a line appended to the file shows up the next time the list is opened', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })
    await openPicker(page)
    await expect(rows(page)).toHaveCount(0)
    await closePicker(page)

    // What an agent does to register a path: append one line.
    mkdirSync(dirname(FAVORITES_FILE), { recursive: true })
    appendFileSync(FAVORITES_FILE, '~/cpc-e2e-favorites/from-agent.md\n')

    await openPicker(page)
    await expect(rows(page)).toHaveCount(1)
    await expect(rows(page)).toContainText('from-agent.md')
    // Removing it from the screen takes the line out of the file.
    await rows(page).locator('[aria-label=remove-favorite]').click()
    await expect(rows(page)).toHaveCount(0)
    await expect.poll(() => hostList(request)).toEqual([])
  })
})
