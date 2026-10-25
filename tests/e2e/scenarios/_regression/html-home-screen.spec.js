// Regression: on the iPhone home-screen web app (= display-mode: standalone) a tapped HTML path
// opened inside the app (first as a new tab that replaced the app, then in the preview sheet). The
// page is handed to Safari instead (= `x-safari-https://`, which iOS opens in Safari), and the app
// stays where it was: no preview sheet, no new window, the chat still on screen. The test browser
// does not hand the address on, so the address itself is checked by the unit tests of
// `_common/externalBrowser.js`.

import { test, expect } from '@playwright/test'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { seedSession, appendEvent } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'

// The home-screen app reports itself through display-mode and navigator.standalone; the test browser is a plain tab
async function asHomeScreen(page) {
  await page.addInitScript(() => {
    const real = window.matchMedia.bind(window)
    window.matchMedia = (query) => (query === '(display-mode: standalone)'
      ? { ...real(query), matches: true, media: query }
      : real(query))
    Object.defineProperty(window.navigator, 'standalone', { value: true, configurable: true })
  })
}

test.describe('regression: an HTML page tapped in the iPhone home-screen app leaves the app', () => {
  test.skip(({ browserName }) => browserName !== 'webkit', 'the home-screen app is an iPhone WebKit')

  test('the page is handed on, and the app stays on the chat', async ({ page, request }) => {
    // /file/open only serves files under HOME, so the sample page is written under ~/.cache
    const dir = join(homedir(), '.cache', 'cpc-e2e', 'home-screen-page')
    mkdirSync(dir, { recursive: true })
    writeFileSync(join(dir, 'index.html'), '<!doctype html><meta charset="utf-8"><p>sample page</p>')
    const html = join(dir, 'index.html')
    try {
      const seeded = await seedSession(request, 'e2e-chat-golden')
      appendEvent(seeded.jsonl_path, {
        type: 'assistant',
        uuid: 'a-home-screen-page',
        message: {
          id: 'msg_home_screen_page',
          role: 'assistant',
          content: [{ type: 'text', text: `The page is at ${html}` }],
          stop_reason: 'end_turn',
          model: 'claude-opus-4-7',
        },
        timestamp: new Date().toISOString(),
      })
      await asHomeScreen(page)
      await openClient(page, { sid: SID })
      const appUrl = page.url()

      const popups = []
      page.context().on('page', (popup) => popups.push(popup.url()))
      await page.locator('.file-link', { hasText: 'index.html' }).last().click()
      await page.waitForTimeout(1_000)
      await expect(page.locator('[data-testid=file-preview-modal]')).toHaveCount(0)
      expect(popups).toEqual([])
      expect(page.url()).toBe(appUrl)
      await expect(page.locator('.file-link', { hasText: 'index.html' }).last()).toBeVisible()
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })
})
