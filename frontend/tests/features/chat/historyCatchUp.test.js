import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const apiFetch = vi.fn()
vi.mock('../../../src/_common/api.js', () => ({ apiFetch: (...args) => apiFetch(...args) }))

import {
  fetchHistory, historyPath, ingestHistory, removeSavedMessages,
} from '../../../src/features/chat/historyCatchUp.js'
import { reconcileUserMessage } from '../../../src/features/chat/reconcileUserMessage.js'

// A screen holds its own cache and lays the backend's history over it by uuid. When the window did
// not reach the screen's position (`reached: false`), the cache must be dropped before the events
// are applied, or the old cache and the window leave a hole between them.

function userEvent(n) {
  return { type: 'user_message', sid: 'ses_a', uuid: `u${n}`, text: `m${n}`, ts: n * 1000 }
}

// A minimal screen: messages of one tab, with the same uuid-matching user_message path the app uses.
function makeScreen(initial) {
  const screen = {
    messages: initial,
    drops: 0,
    dropCache: () => { screen.drops += 1; screen.messages = [] },
    ingest: ev => {
      screen.messages = reconcileUserMessage(screen.messages, ev.text, ev.uuid, ev.send_id, ev.ts, ev.parentUuid)
    },
  }
  return screen
}

function cachedMessages(from, to) {
  const out = []
  for (let n = from; n <= to; n++) out.push({ id: `id${n}`, role: 'user', text: `m${n}`, uuid: `u${n}`, ts: n * 1000 })
  return out
}

describe('historyPath', () => {
  it('adds since when the screen has an offset, and 0 counts as an offset', () => {
    expect(historyPath('ses_a', 1234)).toBe('/jsonl/history/ses_a?since=1234')
    expect(historyPath('ses_a', 0)).toBe('/jsonl/history/ses_a?since=0')
  })

  it('leaves since out when there is no offset', () => {
    expect(historyPath('ses_a', null)).toBe('/jsonl/history/ses_a')
    expect(historyPath('ses_a', undefined)).toBe('/jsonl/history/ses_a')
  })

  it('encodes the tab id', () => {
    expect(historyPath('a b', 5)).toBe('/jsonl/history/a%20b?since=5')
  })
})

describe('fetchHistory', () => {
  beforeEach(() => apiFetch.mockReset())

  it('returns the response body with reached', async () => {
    apiFetch.mockResolvedValue({ ok: true, json: async () => ({ events: [userEvent(1)], pos: 9, reached: true }) })
    const data = await fetchHistory('ses_a', 4)
    expect(apiFetch).toHaveBeenCalledWith('/jsonl/history/ses_a?since=4')
    expect(data).toEqual({ events: [userEvent(1)], pos: 9, reached: true })
  })

  it('returns null when the request fails or the body is not a history', async () => {
    apiFetch.mockResolvedValueOnce({ ok: false })
    expect(await fetchHistory('ses_a', 4)).toBeNull()
    apiFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ nope: 1 }) })
    expect(await fetchHistory('ses_a', 4)).toBeNull()
    apiFetch.mockRejectedValueOnce(new Error('offline'))
    expect(await fetchHistory('ses_a', 4)).toBeNull()
  })
})

describe('ingestHistory', () => {
  it('drops a stale cache before applying when the window did not reach the screen', () => {
    // The screen saw up to m10 and stayed closed; the window starts at m900, so m11-m899 are missing.
    const screen = makeScreen(cachedMessages(1, 10))
    const events = [userEvent(900), userEvent(901)]
    const dropped = ingestHistory({ events, pos: 1, reached: false }, {
      sid: 'ses_a', dropCache: screen.dropCache, ingest: screen.ingest,
    })
    expect(dropped).toBe(true)
    expect(screen.drops).toBe(1)
    expect(screen.messages.map(m => m.uuid)).toEqual(['u900', 'u901'])
  })

  it('drops before the first event, not in the middle', () => {
    const order = []
    ingestHistory({ events: [userEvent(1), userEvent(2)], pos: 1, reached: false }, {
      sid: 'ses_a', dropCache: () => order.push('drop'), ingest: ev => order.push(ev.uuid),
    })
    expect(order).toEqual(['drop', 'u1', 'u2'])
  })

  it('lays the history over the cache when the window reached the screen', () => {
    const screen = makeScreen(cachedMessages(1, 10))
    const events = [userEvent(9), userEvent(10), userEvent(11), userEvent(12)]
    const dropped = ingestHistory({ events, pos: 1, reached: true }, {
      sid: 'ses_a', dropCache: screen.dropCache, ingest: screen.ingest,
    })
    expect(dropped).toBe(false)
    expect(screen.drops).toBe(0)
    expect(screen.messages.map(m => m.uuid)).toEqual(
      ['u1', 'u2', 'u3', 'u4', 'u5', 'u6', 'u7', 'u8', 'u9', 'u10', 'u11', 'u12'])
  })

  it('keeps the cache when the response carries no reached (an older backend)', () => {
    const screen = makeScreen(cachedMessages(1, 3))
    const dropped = ingestHistory({ events: [userEvent(4)], pos: 1 }, {
      sid: 'ses_a', dropCache: screen.dropCache, ingest: screen.ingest,
    })
    expect(dropped).toBe(false)
    expect(screen.messages).toHaveLength(4)
  })

  it('keeps the cache when the caller already dropped it', () => {
    const screen = makeScreen([])
    const dropped = ingestHistory({ events: [userEvent(1)], pos: 1, reached: false }, {
      sid: 'ses_a', dropCache: screen.dropCache, ingest: screen.ingest, dropWhenNotReached: false,
    })
    expect(dropped).toBe(false)
    expect(screen.drops).toBe(0)
    expect(screen.messages).toHaveLength(1)
  })

  it('stops applying once cancelled', () => {
    const seen = []
    let cancelled = false
    ingestHistory({ events: [userEvent(1), userEvent(2), userEvent(3)], pos: 1, reached: true }, {
      sid: 'ses_a', dropCache: () => {},
      ingest: ev => { seen.push(ev.uuid); cancelled = true },
      isCancelled: () => cancelled,
    })
    expect(seen).toEqual(['u1'])
  })
})

describe('removeSavedMessages', () => {
  let store
  beforeEach(() => {
    store = new Map([['cpc_messages_v2_ses_a', 'saved'], ['cpc_messages_v2_ses_b', 'other tab']])
    vi.stubGlobal('localStorage', {
      getItem: k => store.get(k) ?? null,
      removeItem: k => store.delete(k),
    })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('removes only that tab\'s saved messages', () => {
    removeSavedMessages('ses_a')
    expect(store.has('cpc_messages_v2_ses_a')).toBe(false)
    expect(store.has('cpc_messages_v2_ses_b')).toBe(true)
  })

  it('does not throw when storage is unavailable', () => {
    vi.stubGlobal('localStorage', { removeItem: () => { throw new Error('blocked') } })
    expect(() => removeSavedMessages('ses_a')).not.toThrow()
  })
})
