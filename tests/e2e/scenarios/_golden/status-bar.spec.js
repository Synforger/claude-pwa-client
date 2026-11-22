// Golden path: status-bar feature.
// The bar shows the model, ctx and the usage windows the account has now; the settings screen reads the same usage.
// The scenario writes the test backend's own usage log and reads the screen for each shape of an account's usage:
// neither window known, both windows, the 7 days alone.

import { appendFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'
const USAGE_LOG = resolve(
  dirname(fileURLToPath(import.meta.url)), '..', '..', 'fixtures', '_runtime', 'rate-limits.jsonl',
)
// The backend keeps what it read of the usage log for one second.
const USAGE_MEMO_MS = 1_100
const HOUR_SECONDS = 3600

function writeUsage({ five, seven }) {
  const now = Math.floor(Date.now() / 1000)
  appendFileSync(USAGE_LOG, JSON.stringify({
    timestamp: now,
    account_id: 'e2e',
    session_id: 'usage-writer',
    five_hour_pct: five,
    five_hour_resets_at: five === null ? null : now + HOUR_SECONDS,
    seven_day_pct: seven,
    seven_day_resets_at: seven === null ? null : now + 48 * HOUR_SECONDS,
  }) + '\n')
}

async function keepPicture(page, testInfo, name) {
  const path = testInfo.outputPath(`${name}.png`)
  await page.screenshot({ path })
  await testInfo.attach(name, { path, contentType: 'image/png' })
}

test.describe('golden: status-bar', () => {
  test.afterEach(() => writeFileSync(USAGE_LOG, ''))

  test('status bar shows the windows the account has, and never fills an unknown one', async ({ page, request }, testInfo) => {
    writeFileSync(USAGE_LOG, '')
    await seedSession(request, 'e2e-chat-golden')
    await page.waitForTimeout(USAGE_MEMO_MS)
    await openClient(page, { sid: SID })

    const bar = page.locator('[data-testid=status-bar]')
    await expect(bar).toBeVisible({ timeout: 10_000 })
    // Model chip always renders (= cleanModel returns "—" when missing,
    // so the chip is present regardless of payload completeness).
    await expect(bar.locator('[data-testid=status-bar-model]')).toBeVisible()
    await expect(bar).toContainText('ctx')
    await expect(bar).not.toContainText('5h')
    await expect(bar).not.toContainText('7d')
    await keepPicture(page, testInfo, 'bar-neither-window')

    writeUsage({ five: 40, seven: 70 })
    await page.waitForTimeout(USAGE_MEMO_MS)
    await openClient(page, { sid: SID })
    await expect(bar).toContainText('5h 40%')
    await expect(bar).toContainText('7d 70%')
    await keepPicture(page, testInfo, 'bar-both-windows')

    // The 5 hours go away before they were due to reset: the plan has no such window any more.
    writeUsage({ five: null, seven: 11 })
    await page.waitForTimeout(USAGE_MEMO_MS)
    await openClient(page, { sid: SID })
    await expect(bar).toContainText('7d 11%')
    await expect(bar).not.toContainText('5h')
    await keepPicture(page, testInfo, 'bar-week-alone')

    await page.locator('[data-testid=drawer-toggle]').click()
    await page.locator('[data-testid=drawer-settings]').click()
    await page.locator('[data-testid=open-settings]').click()
    const week = page.locator('[data-testid=settings-usage-seven]')
    await expect(week).toContainText('11%')
    await expect(page.locator('[data-testid=settings-usage-five]')).toHaveCount(0)
    await keepPicture(page, testInfo, 'settings-week-alone')
  })
})
