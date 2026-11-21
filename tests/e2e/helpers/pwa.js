// On a wide screen with a mouse the tab list is kept on the left (it starts open, and stays open after a tab is chosen).
// Most scenarios were written for the list laid over the screen (open it with the menu button, choose a tab, it shuts),
// so by default a page answers "no" to that screen's media query and shows the overlay form it always had.
// A scenario of the kept-on-the-left form opens its page with `{ docked: true }`, which leaves the real screen alone.
export const DRAWER_DOCKED_KEY = 'cpc_drawer_docked'

// Must stay in step with DOCKED_SCREEN_QUERY (frontend/src/features/session-drawer/dockedScreen.js).
const DOCKED_SCREEN_QUERY_PARTS = ['min-width: 1024px', 'hover: hover', 'pointer: fine']

// Call before the first goto of a page that does not start through openClient.
export async function keepDrawerOverlaid(page) {
  await page.addInitScript((parts) => {
    const real = window.matchMedia.bind(window)
    window.matchMedia = (query) => {
      if (!parts.every(part => String(query).includes(part))) return real(query)
      return {
        matches: false,
        media: String(query),
        onchange: null,
        addEventListener() {},
        removeEventListener() {},
        addListener() {},
        removeListener() {},
        dispatchEvent: () => false,
      }
    }
  }, DOCKED_SCREEN_QUERY_PARTS)
}

// Common boilerplate: navigate to the SPA and wait long enough for the
// chat-input to render + the unified SSE to settle. The app boots
// transport/lifecycle.js which opens /stream/unified; the backend's tail
// loop polls every 500ms, so anything that asserts on event delivery needs
// the connection up before the test fires its first action. `docked: true` keeps the real screen (see keepDrawerOverlaid).
export async function openClient(page, { sid, docked = false } = {}) {
  if (!docked) await keepDrawerOverlaid(page)
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
