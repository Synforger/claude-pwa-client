// Golden path: ios-native feature.
// On the iPhone-shaped project the ChatInput's ResizeObserver writes a
// --chat-input-h CSS variable on document.documentElement so the overlays
// can avoid the safe-area + keyboard region. Verify the wire-up.

import { test, expect, devices } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'

test.use({ ...devices['iPhone 14'] })

test.describe('golden: ios-native', () => {
  test('chat-input writes --chat-input-h on a mobile viewport', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })

    // The variable is set after the ResizeObserver fires; allow a beat.
    const value = await page.waitForFunction(
      () => {
        const v = getComputedStyle(document.documentElement).getPropertyValue('--chat-input-h').trim()
        return v && v !== '0px' ? v : null
      },
      null,
      { timeout: 10_000 },
    )
    const px = await value.jsonValue()
    expect(px).toBeTruthy()
    expect(px).toMatch(/^\d+(\.\d+)?px$/)
  })
})
