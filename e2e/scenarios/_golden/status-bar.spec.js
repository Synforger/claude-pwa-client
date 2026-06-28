// Golden path: status-bar feature.
// The bar mounts whenever there is an active session and exposes the
// model + budget + mode chips. Their content is driven by the status SSE,
// so we just assert the structural pieces are wired - the values are
// covered by backend unit tests on the status payload itself.

import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'

test.describe('golden: status-bar', () => {
  test('status bar mounts with model chip + 5h / 7d / ctx percent chips', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })

    const bar = page.locator('[data-testid=status-bar]')
    await expect(bar).toBeVisible({ timeout: 10_000 })

    // Model chip always renders (= cleanModel returns "—" when missing,
    // so the chip is present regardless of payload completeness).
    await expect(bar.locator('[data-testid=status-bar-model]')).toBeVisible()
    // 5h / 7d / ctx pct percents are inline spans inside the bar.
    await expect(bar).toContainText('5h')
    await expect(bar).toContainText('7d')
    await expect(bar).toContainText('ctx')
  })
})
