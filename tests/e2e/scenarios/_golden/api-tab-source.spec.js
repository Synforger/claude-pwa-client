// Golden path: API tabs that a program lists in a file of its own (`api_tab_sources`).
//
// A backend of its own runs with one source declared (`run-backend.mjs`, CPC_E2E_API_TABS=1): its tab list file lists
// one tab whose context amount the program says (42,000 of a window of 100,000) with its own spend, and two settings.
// The screen shows the context in percent in the list and the top bar, the tab's own spend, follows the file when the
// program rewrites it (a rollover, a new group), and the settings screen writes the program's settings file.
import { readFileSync, renameSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { test, expect } from '@playwright/test'
import { PeerBackend } from '../../helpers/peer-backends.js'
import { keepDrawerOverlaid } from '../../helpers/pwa.js'

const PORT = 18871
const SOURCE_SID = 'api_g-trip'

test.describe('golden: api-tab-source', () => {
  let backend

  test.beforeAll(async () => {
    backend = new PeerBackend({ name: 'api-tab-source', port: PORT, extraEnv: { CPC_E2E_API_TABS: '1' } })
    await backend.start()
  })

  test.afterAll(async () => {
    await backend?.stop()
  })

  /** Rewrite the tab list file the way the program does (a temporary file renamed over it). */
  function rewriteTabs(change) {
    const path = resolve(backend.runtimeDir, 'api-source', 'tabs.json')
    const tabs = change(JSON.parse(readFileSync(path, 'utf-8')))
    writeFileSync(`${path}.tmp`, JSON.stringify(tabs))
    renameSync(`${path}.tmp`, path)
  }

  test('shows the context in percent and the tab spend, follows the rewritten list, and writes the settings', async ({ page }) => {
    await keepDrawerOverlaid(page)
    await page.goto(`${backend.baseURL}/?ses=${SOURCE_SID}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('Three inns near the station.')).toBeVisible({ timeout: 20_000 })

    // The amount is the program's (42,000), never the record's (999), and reads in percent of the window.
    await expect(page.locator('[data-testid=status-bar-api-context]')).toContainText('42%')
    await expect(page.locator('[data-testid=status-bar-api-spend]')).toContainText('0.5 USD')
    const shared = page.locator('[data-testid=status-bar-api-wallet]')
    await expect(shared).toContainText('123 / 1,000 JPY')
    // Nothing of the bar may be pushed off the screen, on a phone either.
    const end = await page.locator('[data-testid=status-bar] > :last-child').boundingBox()
    expect(end.x + end.width).toBeLessThanOrEqual(page.viewportSize().width)
    await page.screenshot({ path: test.info().outputPath('bar-shared-wallet.png') })
    await page.locator('[data-testid=drawer-toggle]').click()
    const row = page.locator(`[data-cpc-sid=${SOURCE_SID}]`)
    await expect(row.locator('.drawer-item-title')).toHaveText('Trip group')
    await expect(row.locator('[data-testid=session-context]')).toHaveText('42%')
    await expect(page.locator('[data-cpc-sid=api_support-bot] [data-testid=session-context]')).toHaveText('12.3k')

    // The program rolls the conversation over (amount 0), renames the group and starts a second one.
    rewriteTabs(body => ({
      ...body,
      tabs: [
        { ...body.tabs[0], title: 'Trip group (Kyoto)', context_tokens: 0 },
        { ...body.tabs[0], name: 'g-dinner', title: 'Dinner group', context_tokens: 5000,
          record: body.tabs[0].record.replace('g-trip', 'g-dinner') },
      ],
    }))
    await expect(row.locator('[data-testid=session-context]')).toHaveText('0%', { timeout: 10_000 })
    await expect(row.locator('.drawer-item-title')).toHaveText('Trip group (Kyoto)', { timeout: 10_000 })
    await expect(page.locator('[data-cpc-sid=api_g-dinner] [data-testid=session-context]')).toHaveText('5%', { timeout: 10_000 })

    // The settings screen shows the program's fields with their defaults, refuses a value out of range, and writes one.
    await page.locator('[data-testid=drawer-settings]').click()
    await page.locator('[data-testid=open-settings]').click()
    const card = page.locator('[data-testid=settings-api-source-line-group]')
    const rollover = card.locator('[data-testid=settings-api-source-field-rollover_percent]')
    await expect(rollover).toHaveValue('60', { timeout: 10_000 })
    await rollover.fill('99')
    await expect(card.locator('[data-testid=settings-api-source-save]')).toBeDisabled()
    await rollover.fill('55')
    await card.locator('[data-testid=settings-api-source-save]').click()
    await expect(card.locator('.settings-note.ok')).toBeVisible({ timeout: 10_000 })
    const written = JSON.parse(readFileSync(resolve(backend.runtimeDir, 'api-source-config', 'settings.json'), 'utf-8'))
    expect(written).toEqual({ rollover_percent: 55 })
  })
})
