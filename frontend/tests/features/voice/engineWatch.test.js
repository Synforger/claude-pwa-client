import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../../../src/transport/http.ts', () => ({ apiFetch: vi.fn() }))

import { apiFetch } from '../../../src/transport/http.ts'
import { watchEngine, fetchEngine, SOON_MS, LATER_MS } from '../../../src/features/voice/engineWatch.js'

// 時計の代わり: 予約を並べておき、 試験が 1 つずつ回す
function manualClock() {
  const timers = []
  let nextId = 1
  return {
    timers,
    schedule: (fn, ms) => { const id = nextId++; timers.push({ id, fn, ms }); return id },
    cancel: (id) => { const i = timers.findIndex(t => t.id === id); if (i >= 0) timers.splice(i, 1) },
    async runNext() { const t = timers.shift(); await t.fn(); await flush() },
  }
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0))

function watch(answers, { hidden = () => false } = {}) {
  const clock = manualClock()
  const written = []
  const fetchState = vi.fn(async () => {
    const answer = answers.shift()
    if (answer instanceof Error) throw answer
    return answer
  })
  const stop = watchEngine('s1', {
    fetchState, setEngine: (sid, state) => written.push([sid, state]),
    schedule: clock.schedule, cancel: clock.cancel, isHidden: hidden,
  })
  return { clock, written, fetchState, stop }
}

describe('watchEngine — reads the speech engine of a tab while its speaker is on', () => {
  it('reads at once, then every 2 seconds until the engine is up, then every 15 seconds', async () => {
    const { clock, written } = watch(['asleep', 'waking', 'ready', 'ready'])
    await flush()
    expect(written).toEqual([['s1', 'asleep']])
    expect(clock.timers.map(t => t.ms)).toEqual([SOON_MS])
    await clock.runNext()
    expect(clock.timers.map(t => t.ms)).toEqual([SOON_MS])
    await clock.runNext()
    expect(written.at(-1)).toEqual(['s1', 'ready'])
    expect(clock.timers.map(t => t.ms)).toEqual([LATER_MS])
    await clock.runNext()
    expect(written.map(w => w[1])).toEqual(['asleep', 'waking', 'ready', 'ready'])
  })

  it('goes back to every 2 seconds when the engine stops while the speaker is on', async () => {
    const { clock } = watch(['ready', 'asleep'])
    await flush()
    expect(clock.timers.map(t => t.ms)).toEqual([LATER_MS])
    await clock.runNext()
    expect(clock.timers.map(t => t.ms)).toEqual([SOON_MS])
  })

  it('keeps reading every 2 seconds after the engine could not be woken', async () => {
    const { clock, written } = watch(['failed'])
    await flush()
    expect(written).toEqual([['s1', 'failed']])
    expect(clock.timers.map(t => t.ms)).toEqual([SOON_MS])
  })

  it('stops reading for a tab whose engine is not woken on use', async () => {
    const { clock, written } = watch([null])
    await flush()
    expect(written).toEqual([['s1', null]])
    expect(clock.timers).toEqual([])
  })

  it('leaves the engine value as it was when a read fails, and tries again in 2 seconds', async () => {
    const { clock, written } = watch(['waking', new Error('network'), 'ready'])
    await flush()
    await clock.runNext()
    expect(written).toEqual([['s1', 'waking']])
    expect(clock.timers.map(t => t.ms)).toEqual([SOON_MS])
    await clock.runNext()
    expect(written.at(-1)).toEqual(['s1', 'ready'])
  })

  it('does not read while the screen is hidden', async () => {
    let hidden = true
    const { clock, fetchState } = watch(['ready'], { hidden: () => hidden })
    await flush()
    expect(fetchState).not.toHaveBeenCalled()
    expect(clock.timers.map(t => t.ms)).toEqual([SOON_MS])
    hidden = false
    await clock.runNext()
    expect(fetchState).toHaveBeenCalledTimes(1)
  })

  it('clears the value and cancels the next read when stopped', async () => {
    const { clock, written, stop } = watch(['waking'])
    await flush()
    stop()
    expect(clock.timers).toEqual([])
    expect(written.at(-1)).toEqual(['s1', null])
  })

  it('drops an answer that comes back after it was stopped', async () => {
    let answer
    const clock = manualClock()
    const written = []
    const stop = watchEngine('s1', {
      fetchState: () => new Promise(resolve => { answer = resolve }),
      setEngine: (sid, state) => written.push([sid, state]),
      schedule: clock.schedule, cancel: clock.cancel, isHidden: () => false,
    })
    stop()
    answer('ready')
    await flush()
    expect(written).toEqual([['s1', null]])
    expect(clock.timers).toEqual([])
  })
})

describe('fetchEngine — the state of the engine as the backend tells it', () => {
  beforeEach(() => apiFetch.mockReset())

  const reply = (status, body) => ({ status, ok: status >= 200 && status < 300, json: async () => body })

  it('asks the engine route of the tab', async () => {
    apiFetch.mockResolvedValue(reply(200, { engine: 'waking' }))
    expect(await fetchEngine('a b')).toBe('waking')
    expect(apiFetch).toHaveBeenCalledWith('/sessions/a%20b/voice/engine')
  })

  it('answers null for a tab whose engine is not woken on use', async () => {
    apiFetch.mockResolvedValue(reply(200, { engine: null }))
    expect(await fetchEngine('s1')).toBeNull()
  })

  it('answers null for a backend without the route', async () => {
    apiFetch.mockResolvedValue(reply(404, {}))
    expect(await fetchEngine('s1')).toBeNull()
  })

  it('throws when the backend fails, so the watcher keeps the value it has', async () => {
    apiFetch.mockResolvedValue(reply(500, {}))
    await expect(fetchEngine('s1')).rejects.toThrow('HTTP 500')
  })
})
