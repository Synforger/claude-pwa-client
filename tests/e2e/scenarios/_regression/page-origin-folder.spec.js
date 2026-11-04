// Regression: a page served from the page origin's port could fetch nothing but its store, so a page could not read
// the other pages of its own folder (= a contents bar that lists every page of the folder from the folder's top
// page). A page now reads its own folder and what is below it; the folder next to it stays out of reach, and what
// the page keeps in localStorage is still there when it is opened again. The folder's name is Japanese with a space,
// as the agents' tier folders are, since the browser compares the path of the policy in its percent form.

import { test, expect } from '@playwright/test'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

// The folder the test backend serves from the page origin's port (= helpers/run-backend.mjs)
const ORIGIN_DIR = join(homedir(), '.cache', 'cpc-e2e', 'page-origin')

const GUIDE = `<!doctype html><meta charset="utf-8"><title>guide</title>
<p id="own">waiting</p><p id="sibling">waiting</p><p id="kept"></p>
<script>
  async function read(url) {
    try {
      const response = await fetch(url)
      return response.ok ? (await response.text()).trim() : 'status ' + response.status
    } catch {
      return 'blocked'
    }
  }
  read('index.html').then((text) => { document.getElementById('own').textContent = text })
  read('../../other/secret.html').then((text) => { document.getElementById('sibling').textContent = text })
  const before = localStorage.getItem('opened')
  document.getElementById('kept').textContent = before === null ? 'first' : 'again'
  localStorage.setItem('opened', '1')
</script>`

test.describe('regression: a page on the page origin reads its own folder', () => {
  const tab = join(ORIGIN_DIR, '階層 A', 'tab')
  const other = join(ORIGIN_DIR, 'other')

  test.beforeAll(() => {
    mkdirSync(tab, { recursive: true })
    mkdirSync(other, { recursive: true })
    writeFileSync(join(tab, 'index.html'), 'top page')
    writeFileSync(join(tab, 'guide.html'), GUIDE)
    writeFileSync(join(other, 'secret.html'), 'the next folder')
  })

  test.afterAll(() => {
    rmSync(join(ORIGIN_DIR, '階層 A'), { recursive: true, force: true })
    rmSync(other, { recursive: true, force: true })
  })

  test('the top page of the folder is read, the next folder is not, and localStorage is kept', async ({ page, baseURL }) => {
    await page.goto(`/file/open?path=${encodeURIComponent(join(tab, 'guide.html'))}`)
    expect(new URL(page.url()).port).not.toBe(new URL(baseURL).port)

    await expect(page.locator('#own')).toHaveText('top page')
    await expect(page.locator('#sibling')).toHaveText('blocked')
    await expect(page.locator('#kept')).toHaveText('first')

    await page.reload()
    await expect(page.locator('#kept')).toHaveText('again')
  })
})
