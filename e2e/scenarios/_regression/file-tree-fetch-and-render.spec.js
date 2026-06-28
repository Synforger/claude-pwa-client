// Regression: file-tree menu must actually fetch /files/tree AND render the
// returned entries, not just mount the modal shell.
//
// Bug shape: an SPA cache / wiring regression can leave the modal mounting but
// never firing the fetch (= empty modal forever), or fire the fetch but never
// hand the result to React state (= permanent "読み込み中..." or silent
// "読み込みエラー"). The existing golden only asserts the modal element is
// visible, so both failure modes slip through. This spec wires the assertion
// chain end-to-end:
//
//   1. Network: a GET /files/tree?path=~ goes out and returns 200 with a
//      non-empty entries array.
//   2. DOM: at least one [data-testid=tree-entry] node renders inside the
//      modal (= the consumer side accepted the payload and React committed).
//   3. Negative: no `.error.tree-loading` element survives in the modal.
//
// Triggers covered:
//   - Menu button stops dispatching setTreeOpen
//   - apiFetch base URL or path misformat
//   - response.json() shape change (entries renamed / dropped)
//   - useEffect dep regression that leaves loading=true forever

import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2eftreef1'

test.describe('regression: file-tree-fetch-and-render', () => {
  test('menu click triggers /files/tree fetch and renders entries', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })

    // Pre-arm the response listener BEFORE the click so the fetch can't sneak
    // past us. The encoded `~` is `%7E`; allow either casing.
    const fetchPromise = page.waitForResponse(
      (res) => /\/files\/tree\?path=(%7E|%7e|~)/.test(res.url()) && res.request().method() === 'GET',
      { timeout: 10_000 },
    )

    await page.locator('[data-testid=chat-menu-toggle]').click()
    await page.getByRole('button', { name: 'ファイルツリー' }).click()

    const res = await fetchPromise
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(Array.isArray(body.entries)).toBe(true)
    expect(body.entries.length).toBeGreaterThan(0)

    // Modal mounted (= same assertion as the golden, kept as a tripwire so a
    // future Suspense / lazy regression surfaces here too).
    const modal = page.locator('[data-testid=file-tree-modal]')
    await expect(modal).toBeVisible({ timeout: 5_000 })

    // The payload made it into React state and committed to DOM. Without
    // this, an "empty modal" regression silently passes.
    const entries = modal.locator('[data-testid=tree-entry]')
    await expect(entries.first()).toBeVisible({ timeout: 5_000 })
    expect(await entries.count()).toBeGreaterThan(0)

    // No surviving error chip in the modal (= "読み込みエラー (...)" path).
    await expect(modal.locator('.error.tree-loading')).toHaveCount(0)
  })
})
