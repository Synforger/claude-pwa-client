// Golden path: plan-approval feature.
// Inject pending_plan straight into agent_status via /debug/e2e/inject-
// pending-plan so the status SSE picks it up on its next tick. The 📑
// topbar button then materialises and clicking it mounts the bubble.

import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'

test.describe('golden: plan-approval', () => {
  test('pending_plan surfaces the 📑 button and opens the bubble', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })

    const inject = await request.post(`/debug/e2e/inject-pending-plan/${SID}`, {
      data: {
        plan: 'do step A then step B',
        tool_use_id: 'tool_plan_e2e',
        choices: [
          { key: '1', label: 'auto-accept' },
          { key: '3', label: 'keep planning' },
        ],
      },
    })
    expect(inject.status()).toBe(200)

    const planBtn = page.locator('[data-testid=plan-approval-open-button]')
    await expect(planBtn).toBeVisible({ timeout: 15_000 })
    await planBtn.click()

    const bubble = page.locator('[data-testid=plan-approval-bubble]')
    await expect(bubble).toBeVisible({ timeout: 5_000 })
    // Both choices render as buttons.
    await expect(bubble.locator('[data-testid=plan-approval-choice]')).toHaveCount(2)
  })
})
