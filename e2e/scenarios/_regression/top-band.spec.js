// Regression: in the iPhone app the page reaches under the device's top band (= the clock and
// the battery; viewport-fit=cover), and a header drawn at the very top of the screen sat in that
// band. The image preview's ✕ could not be tapped there, and the preview could not be left.
// Chromium emulates the band (= the safe-area inset the app reports), so the headers are checked
// to sit below it.

import { test, expect } from '@playwright/test'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { seedSession, appendEvent } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'
import { testCard } from '../../helpers/png.js'

const SID = 'ses_e2echatgld'
// The top band of an iPhone with the Dynamic Island, in CSS pixels
const TOP_BAND = 62

async function withTopBand(page) {
  const cdp = await page.context().newCDPSession(page)
  await cdp.send('Emulation.setSafeAreaInsetsOverride', { insets: { top: TOP_BAND, bottom: 34, left: 0, right: 0 } })
}

function topOf(locator) {
  return locator.evaluate((el) => el.getBoundingClientRect().top)
}

test.describe('regression: what sits at the top of the screen clears the device top band', () => {
  test.skip(({ browserName }) => browserName !== 'chromium', 'the top band is emulated through Chromium')

  test('the image preview shows its ✕ below the band, and the ✕ closes the preview', async ({ page, request }) => {
    // /file/raw only serves files under HOME, so the sample image is written under ~/.cache
    const dir = join(homedir(), '.cache', 'cpc-e2e')
    const png = join(dir, 'top-band-sample.png')
    mkdirSync(dir, { recursive: true })
    writeFileSync(png, testCard(320, 200))
    try {
      const seeded = await seedSession(request, 'e2e-chat-golden')
      appendEvent(seeded.jsonl_path, {
        type: 'assistant',
        uuid: 'a-top-band',
        message: {
          id: 'msg_top_band',
          role: 'assistant',
          content: [{ type: 'text', text: `The plot is at ${png}` }],
          stop_reason: 'end_turn',
          model: 'claude-opus-4-7',
        },
        timestamp: new Date().toISOString(),
      })
      await withTopBand(page)
      await openClient(page, { sid: SID })

      await page.locator('.file-link', { hasText: 'top-band-sample.png' }).last().click()
      const modal = page.locator('[data-testid=file-preview-modal]')
      await expect(modal).toBeVisible({ timeout: 10_000 })
      const close = modal.locator('.modal-close')
      expect(await topOf(close)).toBeGreaterThanOrEqual(TOP_BAND)
      expect(await topOf(modal.locator('[data-testid=file-preview-path]'))).toBeGreaterThanOrEqual(TOP_BAND)
      await close.click()
      await expect(modal).toHaveCount(0)
    } finally {
      rmSync(png, { force: true })
    }
  })

  test('the file tree shows its header below the band', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await withTopBand(page)
    await openClient(page, { sid: SID })

    await page.locator('[data-testid=more-menu-toggle]').click()
    await page.locator('[data-testid=more-menu-file-tree]').click()
    const tree = page.locator('[data-testid=file-tree-modal]')
    await expect(tree).toBeVisible({ timeout: 5_000 })
    const header = tree.locator('.tree-header')
    const firstControl = header.locator('button').first()
    expect(await topOf(firstControl)).toBeGreaterThanOrEqual(TOP_BAND)
  })
})
