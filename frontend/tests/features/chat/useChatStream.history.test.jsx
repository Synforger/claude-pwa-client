// @vitest-environment jsdom
//
// How useChatStream catches up the history of the tab on screen:
// - opening a tab asks for the history with the screen's offset as `since` (left out when there is none)
// - `reached: false` drops the tab's cache (memory and the saved copy) before the events are applied
// - `reached: true` lays the events over the cache
// - the `history_refetch` mark from the stream's replay drops the cache and fetches the history again
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useState } from 'react'
import { renderHook, act, waitFor } from '@testing-library/react'

const apiFetch = vi.fn()
vi.mock('../../../src/_common/api.js', () => ({ apiFetch: (...args) => apiFetch(...args) }))

const transport = vi.hoisted(() => ({
  handler: null,
  offset: null,
  advanceOffset: vi.fn(),
}))
vi.mock('../../../src/transport/select.ts', () => ({
  chatTransport: {
    subscribe: handler => { transport.handler = handler; return () => {} },
    setSubscribedSids: vi.fn(),
    setVoiceSids: vi.fn(),
    getOffset: () => transport.offset,
    advanceOffset: (...args) => transport.advanceOffset(...args),
    resetOffset: vi.fn(),
    bumpReconnect: vi.fn(),
    flushOffsets: vi.fn(),
  },
}))
vi.mock('../../../src/transport/connectionStatus.js', () => ({ useConnectionStatus: () => true }))
vi.mock('../../../src/features/voice/index.js', () => ({
  observeVoiceEvent: vi.fn(),
  subscribeVoice: () => () => {},
  voiceOnSids: () => '',
}))

import { useChatStream } from '../../../src/features/chat/useChatStream.js'

const SID = 'ses_a'

function userEvent(n) {
  return { type: 'user_message', sid: SID, uuid: `u${n}`, text: `m${n}`, ts: n * 1000 }
}

function cached(from, to) {
  const out = []
  for (let n = from; n <= to; n++) out.push({ id: `id${n}`, role: 'user', text: `m${n}`, uuid: `u${n}`, ts: n * 1000 })
  return out
}

function respondWithHistory(responses) {
  const queue = [...responses]
  apiFetch.mockImplementation(async path => {
    if (!path.startsWith('/jsonl/history/')) return { ok: false }
    const body = queue.length > 1 ? queue.shift() : queue[0]
    return { ok: true, json: async () => body }
  })
}

function historyPaths() {
  return apiFetch.mock.calls.map(call => call[0]).filter(path => path.startsWith('/jsonl/history/'))
}

function mountTab(initialMessages) {
  return renderHook(() => {
    const [messages, setMessages] = useState({ [SID]: initialMessages })
    useChatStream({
      activeSession: { id: SID },
      setMessages,
      input: {}, setInput: () => {},
      attachments: {}, clearAttachments: () => {},
      scrollToBottom: () => {}, isAtBottomRef: { current: true },
      sendStopIntent: () => {}, onSendFailed: () => {}, onStopUnavailable: () => {},
    })
    return messages[SID]
  })
}

const uuids = messages => messages.map(m => m.uuid)

// Node's own experimental localStorage hides jsdom's, so the storage is stubbed by hand.
function makeStorage() {
  const map = new Map()
  return {
    getItem: key => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, String(value)),
    removeItem: key => map.delete(key),
  }
}

beforeEach(() => {
  apiFetch.mockReset()
  transport.handler = null
  transport.offset = null
  transport.advanceOffset.mockReset()
  vi.stubGlobal('localStorage', makeStorage())
})

afterEach(() => vi.unstubAllGlobals())

describe('useChatStream history catch-up', () => {
  it('asks with the screen\'s offset as since, and lays the events over the cache when the window reached', async () => {
    transport.offset = 4321
    respondWithHistory([{ events: [userEvent(2), userEvent(3), userEvent(4)], pos: 9000, reached: true }])
    const { result } = mountTab(cached(1, 3))
    await waitFor(() => expect(uuids(result.current)).toEqual(['u1', 'u2', 'u3', 'u4']))
    expect(historyPaths()).toEqual(['/jsonl/history/ses_a?since=4321'])
    expect(transport.advanceOffset).not.toHaveBeenCalled()
  })

  it('drops the cache and the saved copy, then applies only the returned events, when the window did not reach', async () => {
    transport.offset = 4321
    localStorage.setItem('cpc_messages_v2_ses_a', 'saved copy')
    respondWithHistory([{ events: [userEvent(900), userEvent(901)], pos: 9000, reached: false }])
    const { result } = mountTab(cached(1, 10))
    await waitFor(() => expect(uuids(result.current)).toEqual(['u900', 'u901']))
    expect(localStorage.getItem('cpc_messages_v2_ses_a')).toBeNull()
    expect(transport.advanceOffset).toHaveBeenCalledWith(SID, 9000)
  })

  it('leaves since out when the screen has no offset', async () => {
    respondWithHistory([{ events: [userEvent(1)], pos: 100, reached: false }])
    const { result } = mountTab([])
    await waitFor(() => expect(uuids(result.current)).toEqual(['u1']))
    expect(historyPaths()).toEqual(['/jsonl/history/ses_a'])
  })

  it('keeps the cache when the screen has no offset, since it cannot tell whether anything is missing', async () => {
    respondWithHistory([{ events: [userEvent(4)], pos: 100, reached: false }])
    const { result } = mountTab(cached(1, 3))
    await waitFor(() => expect(uuids(result.current)).toEqual(['u1', 'u2', 'u3', 'u4']))
    expect(transport.advanceOffset).not.toHaveBeenCalled()
  })

  it('keeps the cache when the history could not be fetched', async () => {
    apiFetch.mockResolvedValue({ ok: false })
    const { result } = mountTab(cached(1, 3))
    await waitFor(() => expect(apiFetch).toHaveBeenCalled())
    expect(uuids(result.current)).toEqual(['u1', 'u2', 'u3'])
  })

  it('drops the cache at once on the history_refetch mark, then fetches the history without since', async () => {
    transport.offset = 4321
    respondWithHistory([
      { events: [userEvent(3)], pos: 5000, reached: true },
      { events: [userEvent(950), userEvent(951)], pos: 9500, reached: false },
    ])
    const { result } = mountTab(cached(1, 3))
    await waitFor(() => expect(historyPaths()).toHaveLength(1))
    await waitFor(() => expect(transport.handler).not.toBeNull())

    act(() => { transport.handler({ type: 'history_refetch', sid: SID, corr_id: 'c' }) })
    // the cache is gone before the history arrives, so frames after the mark land in a clean tab
    expect(result.current).toEqual([])

    await waitFor(() => expect(uuids(result.current)).toEqual(['u950', 'u951']))
    expect(historyPaths()[1]).toBe('/jsonl/history/ses_a')
    // the mark already dropped the cache: the second response's reached: false drops nothing more
    expect(transport.advanceOffset).not.toHaveBeenCalled()
  })
})
