// Sample ticket rows for the screen: puts rows into every `tickets` frame the screen takes from the unified stream, so a
// scenario can draw tickets in states the test backend's doors cannot make (a waiting ticket, a mark, a due date) with the
// real backend and the real stream under it. `rows` are added to the backend's rows; `overrides` (`{ [ticket id]: fields }`)
// change fields of a real row by id.
//
// TODO: drop `rows` and use the backend's own doors once `tabs ticket add --waiting` and `--due` have landed (the marks are
// computed by the backend then).

export async function sampleTickets(page, { rows = [], overrides = {} }) {
  await page.addInitScript(({ rows, overrides }) => {
    const Native = window.EventSource
    const rewrite = (data) => {
      const frame = JSON.parse(data)
      if (frame.ch !== 'tickets' || !frame.data || !Array.isArray(frame.data.tickets)) return data
      const real = frame.data.tickets.map((row) => ({ ...row, ...(overrides[row.id] || {}) }))
      return JSON.stringify({ ...frame, data: { ...frame.data, tickets: [...real, ...rows] } })
    }
    function SampledEventSource(url, init) {
      const source = new Native(url, init)
      if (!String(url).includes('/stream/unified')) return source
      Object.defineProperty(source, 'onmessage', {
        configurable: true,
        set(handler) {
          source.addEventListener('message', (event) => {
            let out = event
            try { out = new MessageEvent('message', { data: rewrite(event.data) }) } catch { /* not a tickets frame: pass it on */ }
            handler.call(source, out)
          })
        },
      })
      return source
    }
    SampledEventSource.prototype = Native.prototype
    for (const state of ['CONNECTING', 'OPEN', 'CLOSED']) SampledEventSource[state] = Native[state]
    window.EventSource = SampledEventSource
  }, { rows, overrides })
}
