// Golden path: screenshare feature.
// useMoonlightAvailable normally probes /moonlight/ and returns false in e2e.
// The localStorage `cpc_e2e_moonlight=1` seam forces it to true so the
// scenario can click the toggle and observe the iframe mount.

import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'

test.describe('golden: screenshare', () => {
  test('toggle mounts the moonlight iframe', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')

    // Force the availability flag before mount.
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await page.evaluate(() => localStorage.setItem('cpc_e2e_moonlight', '1'))
    await page.goto(`/?ses=${encodeURIComponent(SID)}`, { waitUntil: 'domcontentloaded' })
    await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible' })
    await page.waitForTimeout(1500)

    await page.locator('[data-testid=screenshare-toggle]').click()
    await expect(page.locator('[data-testid=moonlight-frame]')).toBeVisible({ timeout: 10_000 })
  })
})
