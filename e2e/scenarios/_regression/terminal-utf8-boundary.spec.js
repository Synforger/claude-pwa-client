// Regression for the terminal UTF-8 boundary cluster (= 2026-06-25 trace +
// ADR-013 "bytes 主経路 + TextDecoder({stream:true})"). Symptom: when a
// multi-byte UTF-8 codepoint arrives split across two WebSocket frames the
// old text-based pipeline rendered '?' / '�' instead of the codepoint
// because each frame was decoded standalone.
//
// Scenario shape (ADR-022):
//   1. Seed an empty session, switch the view to terminal.
//   2. Open the /ws/pty/{sid} websocket lazily by waiting for terminal-pane
//      to mount.
//   3. POST /debug/e2e/pty-write with the first half of "日" (= e6 97).
//   4. POST /debug/e2e/pty-write with the second half (= a5).
//   5. Assert window.__cpcTerm.snapshot() contains "日" (= TextDecoder
//      stitched the codepoint across the boundary).

import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2eterm01'

async function ptyWrite(request, sid, bytes) {
  const b64 = Buffer.from(bytes).toString('base64')
  const res = await request.post(`/debug/e2e/pty-write/${encodeURIComponent(sid)}`, {
    data: { bytes_b64: b64 },
  })
  if (!res.ok()) {
    throw new Error(`pty-write failed: ${res.status()} ${await res.text()}`)
  }
}

test.describe('regression: terminal-utf8-boundary', () => {
  test('multi-byte UTF-8 split across frames decodes correctly', async ({ page, request }) => {
    await seedSession(request, 'e2e-terminal')

    await openClient(page, { sid: SID })

    // Switch view to terminal via the chat menu.
    await page.locator('[data-testid=chat-menu-toggle]').click()
    await page.locator('[data-testid=view-toggle]').click()

    // Wait for the terminal pane to mount (= lazy chunk + xterm.js init).
    await page.locator('[data-testid=terminal-pane]').waitFor({ state: 'visible', timeout: 10_000 })
    await page.waitForFunction(() => !!window.__cpcTerm, null, { timeout: 10_000 })
    // Give the /ws/pty handshake a moment to land + flush the initial backlog.
    await page.waitForTimeout(750)

    // "日" = U+65E5 = E6 97 A5 in UTF-8. Split across two frames.
    await ptyWrite(request, SID, [0xe6, 0x97])
    await page.waitForTimeout(150) // give pump_to_client a tick to flush
    await ptyWrite(request, SID, [0xa5])

    await page.waitForFunction(
      () => (window.__cpcTerm?.snapshot?.() || '').includes('日'),
      null,
      { timeout: 5_000 },
    )

    const snapshot = await page.evaluate(() => window.__cpcTerm.snapshot())
    expect(snapshot).toContain('日')
    // No replacement chars from a botched standalone decode.
    expect(snapshot).not.toContain('�')
  })
})
