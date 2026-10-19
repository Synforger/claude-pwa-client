// Regression: on the iPhone home-screen web app (= display-mode: standalone) a tapped HTML path
// opened /file/view as a new tab, which the home-screen app shows in place of itself with no
// control to come back: the chat could only be reached again by closing the app. The page now
// opens in the preview sheet, drawn in a frame (= its script runs and its relative image
// loads), and the sheet's ✕ brings the chat back without leaving the app's page.

import { test, expect } from '@playwright/test'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { seedSession, appendEvent } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'
import { testCard } from '../../helpers/png.js'

const SID = 'ses_e2echatgld'

// The home-screen app reports itself through display-mode; the test browser is a plain tab
async function asHomeScreen(page) {
  await page.addInitScript(() => {
    const real = window.matchMedia.bind(window)
    window.matchMedia = (query) => (query === '(display-mode: standalone)'
      ? { ...real(query), matches: true, media: query }
      : real(query))
  })
}

test.describe('regression: an HTML page opened from the iPhone home-screen app can be left', () => {
  test.skip(({ browserName }) => browserName !== 'webkit', 'the home-screen app is an iPhone WebKit')

  test('the page is drawn in the preview sheet, and its ✕ returns to the chat', async ({ page, request }) => {
    // /file/open only serves files under HOME, so the sample page is written under ~/.cache
    const dir = join(homedir(), '.cache', 'cpc-e2e', 'home-screen-page')
    mkdirSync(join(dir, 'cam'), { recursive: true })
    writeFileSync(join(dir, 'cam', 'a.png'), testCard(120, 80))
    writeFileSync(join(dir, 'index.html'), `<!doctype html><meta charset="utf-8">
<p id="drawn"></p><img id="pic" src="cam/a.png" alt="">
<p id="isolated"></p>
<script>
document.getElementById('drawn').textContent = 'drawn by the page script'
let reach; try { reach = String(parent.document.title) } catch { reach = 'blocked' }
document.getElementById('isolated').textContent = self.origin + ' ' + reach
</script>`)
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

      await page.locator('.file-link', { hasText: 'index.html' }).last().click()
      const modal = page.locator('[data-testid=file-preview-modal]')
      await expect(modal).toBeVisible({ timeout: 10_000 })
      expect(page.url()).toBe(appUrl)

      const frame = page.frameLocator('[data-testid=file-preview-page]')
      await expect(frame.locator('#drawn')).toHaveText('drawn by the page script', { timeout: 10_000 })
      await expect.poll(() => frame.locator('#pic').evaluate((img) => img.naturalWidth)).toBe(120)
      // The page stays apart from the app: the backend's sandbox gives it no origin of its own
      expect(await frame.locator('#isolated').textContent()).toBe('null blocked')

      await modal.locator('.modal-close').click()
      await expect(modal).toHaveCount(0)
      expect(page.url()).toBe(appUrl)
      await expect(page.locator('.file-link', { hasText: 'index.html' }).last()).toBeVisible()
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })
})
