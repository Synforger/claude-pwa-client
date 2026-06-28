// Golden path: terminal feature.
// View toggle flips chat -> terminal and the terminal pane mounts with its
// xterm container, input row, and quick-control buttons (Ctrl-C / Tab / etc).

import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'

test.describe('golden: terminal', () => {
  test('view toggle mounts the terminal pane', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })

    await page.locator('[data-testid=chat-menu-toggle]').click()
    await page.locator('[data-testid=view-toggle]').click()

    const pane = page.locator('[data-testid=terminal-pane]')
    await expect(pane).toBeVisible({ timeout: 10_000 })
    await expect(page.locator('[data-testid=terminal-output]')).toBeVisible()
    await expect(page.locator('[data-testid=terminal-input]')).toBeVisible()
    // xterm initialised + seam installed.
    await page.waitForFunction(() => !!window.__cpcTerm?.snapshot, null, { timeout: 5_000 })
  })
})
