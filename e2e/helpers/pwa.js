// Common boilerplate: navigate to the SPA, wait for the first SSE pulse so
// downstream `expect`s aren't racing initial load.
export async function openClient(page, { sid } = {}) {
  const url = sid ? `/?ses=${encodeURIComponent(sid)}` : '/'
  await page.goto(url, { waitUntil: 'domcontentloaded' })
  // The app boots transport/lifecycle.js which opens the unified SSE before
  // any chat painting. Wait for *something* to confirm the stream connected,
  // either an SSE event landing on window or simply the body marking ready.
  await page.waitForFunction(
    () => document.body?.dataset?.['cpcReady'] === '1'
      || !!document.querySelector('[data-cpc-stream-open="1"]')
      || document.readyState === 'complete',
    { timeout: 15_000 },
  ).catch(() => { /* ready signal is best-effort; tests assert on real DOM */ })
  return page
}

export function sessionUrl(sid) {
  return `/?ses=${encodeURIComponent(sid)}`
}
