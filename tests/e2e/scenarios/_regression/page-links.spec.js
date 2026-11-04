// Regression: a link inside an HTML page opened in the browser sent the browser to the client's screen (= the file
// opened in the client's preview, inside a second copy of the client) when it pointed at an image, Markdown or any
// other file that is not HTML, and a `target="_blank"` link did nothing at all. Every link of a page now opens in
// that browser: an image as the image, Markdown and code as text, an unknown binary as a download, another page as
// that page, and a new-tab link in a new tab.

import { test, expect } from '@playwright/test'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

// A 1x1 transparent PNG
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
  'base64',
)

const PAGE = `<!doctype html><meta charset="utf-8"><title>links</title>
<ul>
  <li><a id="image" href="img/dot.png">image</a></li>
  <li><a id="markdown" href="notes.md">markdown</a></li>
  <li><a id="other-page" href="other.html">other page</a></li>
  <li><a id="new-tab" href="img/dot.png" target="_blank">image in a new tab</a></li>
  <li><a id="binary" href="data.bin">binary</a></li>
</ul>`

test.describe('regression: the links of a page open in that browser', () => {
  // /file/open only serves files under HOME, so the sample page is written under ~/.cache
  const dir = join(homedir(), '.cache', 'cpc-e2e', 'page-links')
  const html = join(dir, 'index.html')

  test.beforeAll(() => {
    mkdirSync(join(dir, 'img'), { recursive: true })
    writeFileSync(html, PAGE)
    writeFileSync(join(dir, 'other.html'), '<!doctype html><meta charset="utf-8"><p id="other">the other page</p>')
    writeFileSync(join(dir, 'img', 'dot.png'), PNG)
    writeFileSync(join(dir, 'notes.md'), '# Notes\n\nplain text in the browser\n')
    writeFileSync(join(dir, 'data.bin'), Buffer.from([0, 1, 2, 3]))
  })

  test.afterAll(() => {
    rmSync(dir, { recursive: true, force: true })
  })

  async function openPage(page) {
    await page.goto(`/file/open?path=${encodeURIComponent(html)}`)
    await expect(page.locator('#image')).toBeVisible()
    return page.url()
  }

  test('an image, Markdown and another page open in the same tab, not in the client', async ({ page }) => {
    const pageUrl = await openPage(page)
    expect(pageUrl).toContain('/file/view/')

    const [image] = await Promise.all([page.waitForNavigation(), page.locator('#image').click()])
    expect(image.status()).toBe(200)
    expect(image.headers()['content-type']).toBe('image/png')
    expect(page.url()).toBe(new URL('img/dot.png', pageUrl).href)

    await page.goto(pageUrl)
    const [markdown] = await Promise.all([page.waitForNavigation(), page.locator('#markdown').click()])
    expect(markdown.headers()['content-type']).toBe('text/plain; charset=utf-8')
    expect(page.url()).toBe(new URL('notes.md', pageUrl).href)
    await expect(page.locator('body')).toContainText('plain text in the browser')

    await page.goto(pageUrl)
    await page.locator('#other-page').click()
    await expect(page.locator('#other')).toHaveText('the other page')
    expect(page.url()).not.toContain('preview=')
  })

  test('a new-tab link opens a new tab, and an unknown binary downloads', async ({ page }) => {
    await openPage(page)

    const [popup] = await Promise.all([page.context().waitForEvent('page'), page.locator('#new-tab').click()])
    await popup.waitForLoadState()
    expect(popup.url()).toContain('/img/dot.png')
    expect(popup.url()).not.toContain('preview=')
    await popup.close()

    const [download] = await Promise.all([page.waitForEvent('download'), page.locator('#binary').click()])
    expect(download.suggestedFilename()).toBe('data.bin')
  })
})
