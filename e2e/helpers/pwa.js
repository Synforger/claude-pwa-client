// Common boilerplate: navigate to the SPA and wait long enough for the
// chat-input to render + the unified SSE to settle. The app boots
// transport/lifecycle.js which opens /jsonl/stream/all; the backend's tail
// loop polls every 500ms, so anything that asserts on event delivery needs
// the connection up before the test fires its first action.
export async function openClient(page, { sid } = {}) {
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
