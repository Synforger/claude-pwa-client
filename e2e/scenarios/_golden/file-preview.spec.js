// Golden path: file-preview feature.
// Inject a favorites entry pointing at the repo's own README, open the
// favorites quick picker, click the entry, assert the preview modal mounts
// with the right path.

import { test, expect } from '@playwright/test'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { seedSession, appendEvent } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'

test.describe('golden: file-preview', () => {
  test('preview modal opens from favorites quick picker', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })

    // Pin a favorite to a file the backend will happily serve under HOME.
    const fixturePath = process.env.HOME + '/repos/claude-pwa-client.v2/README.md'
    await page.evaluate((path) => {
      localStorage.setItem('cpc.fileTree.favorites', JSON.stringify([{ path, name: 'README.md' }]))
      window.dispatchEvent(new CustomEvent('cpc-favorites-changed'))
    }, fixturePath)
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible' })
    await page.waitForTimeout(1500)

    await page.locator('[data-testid=favorites-open-button]').click()
    // The favorites picker shows the pinned row; click it.
    await page.getByText('README.md').first().click()

    const modal = page.locator('[data-testid=file-preview-modal]')
    await expect(modal).toBeVisible({ timeout: 10_000 })
    await expect(modal.locator('[data-testid=file-preview-path]')).toContainText('README.md')
  })

  test('an image path in the chat opens as an image', async ({ page, request }) => {
    // /file/raw only serves files under HOME, and the worktree running e2e may live
    // outside it, so the sample image is written under ~/.cache for this test.
    const dir = join(homedir(), '.cache', 'cpc-e2e')
    const png = join(dir, 'preview-sample.png')
    mkdirSync(dir, { recursive: true })
    writeFileSync(png, Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAEUlEQVR4nGP4z8DwH4QZYAwAR8oH+WdZbrcAAAAASUVORK5CYII=',
      'base64',
    ))
    try {
      const seeded = await seedSession(request, 'e2e-chat-golden')
      appendEvent(seeded.jsonl_path, {
        type: 'assistant',
        uuid: 'a-image-preview',
        message: {
          id: 'msg_image_preview',
          role: 'assistant',
          content: [{ type: 'text', text: `Saved the screenshot to ${png}` }],
          stop_reason: 'end_turn',
          model: 'claude-opus-4-7',
        },
        timestamp: new Date().toISOString(),
      })
      await openClient(page, { sid: SID })

      await page.locator('.file-link', { hasText: 'preview-sample.png' }).last().click()
      const modal = page.locator('[data-testid=file-preview-modal]')
      await expect(modal).toBeVisible({ timeout: 10_000 })
      const img = modal.locator('[data-testid=file-preview-image]')
      await expect(img).toBeVisible()
      await expect.poll(() => img.evaluate((el) => el.naturalWidth)).toBe(2)
      // The loading label goes away once the image is in (a cached image can load
      // before the preview's own reset runs).
      await expect(modal.getByText('Loading...')).toHaveCount(0)
    } finally {
      rmSync(png, { force: true })
    }
  })
})
