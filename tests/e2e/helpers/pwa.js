// On a wide screen with a mouse the tab list starts open (kept on the left) unless the machine remembered it shut
// (localStorage `cpc_drawer_docked`). The scenarios open it with the ☰ button, which would shut an open one, so a
// page starts with it remembered as shut unless the scenario says `drawerDefault: true` to see the real start.
// The value is written before the page's own scripts run and only when nothing was remembered, so a reload keeps
// what the scenario did.
export const DRAWER_DOCKED_KEY = 'cpc_drawer_docked'

// Common boilerplate: navigate to the SPA and wait long enough for the
// chat-input to render + the unified SSE to settle. The app boots
// transport/lifecycle.js which opens /stream/unified; the backend's tail
// loop polls every 500ms, so anything that asserts on event delivery needs
// the connection up before the test fires its first action. `drawerDefault: true` skips the remembered-shut start above.
export async function openClient(page, { sid, drawerDefault = false } = {}) {
  if (!drawerDefault) {
    await page.addInitScript((key) => {
      if (window.localStorage.getItem(key) === null) window.localStorage.setItem(key, 'false')
    }, DRAWER_DOCKED_KEY)
  }
  const url = sid ? `/?ses=${encodeURIComponent(sid)}` : '/'
  await page.goto(url, { waitUntil: 'domcontentloaded' })

  // chat-input painting means React mounted and the active session resolved.
  await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible', timeout: 15_000 })

  // Settle: SSE handshake + initial /sessions/overview + first JSONL tail
  // need a moment before user actions land deterministically. 1500ms is
  // chosen to comfortably cover the 500ms backend poll cycle plus React
  // hydration of the message list from localStorage.
  await page.waitForTimeout(1500)
  return page
}

export function sessionUrl(sid) {
  return `/?ses=${encodeURIComponent(sid)}`
}
