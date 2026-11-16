// @vitest-environment jsdom
//
// Sends made one after another in a tab: a send made while an earlier one is still in flight (the backend waits up
// to 4 s to see the text in the conversation) is neither dropped nor sent ahead of it. Its bubble appears at once and
// its POST goes out once the earlier POST ended. Attachments an earlier send still carries are not sent twice.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useState } from 'react'
import { renderHook, act, waitFor } from '@testing-library/react'

const apiFetch = vi.fn()
vi.mock('../../../src/_common/api.js', () => ({ apiFetch: (...args) => apiFetch(...args) }))
vi.mock('../../../src/transport/select.ts', () => ({
  chatTransport: {
    subscribe: () => () => {},
    setSubscribedSids: vi.fn(),
    setVoiceSids: vi.fn(),
    getOffset: () => null,
    advanceOffset: vi.fn(),
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

/** POSTs to the send doors that wait until the test answers them, in the order they were made. */
function holdSends() {
  const held = []
  apiFetch.mockImplementation((path, options) => {
    if (!path.startsWith(`/pty/${SID}/send`)) return Promise.resolve({ ok: true, json: async () => ({}) })
    return new Promise(resolve => {
      held.push({ path, options, answer: () => resolve({ ok: true, json: async () => ({ ok: true }) }) })
    })
  })
  return held
}

function mountTab(attachments = {}) {
  const clearAttachments = vi.fn()
  const view = renderHook(() => {
    const [messages, setMessages] = useState({ [SID]: [] })
    const stream = useChatStream({
      activeSession: { id: SID },
      setMessages,
      input: {}, setInput: () => {},
      attachments, clearAttachments,
      scrollToBottom: () => {}, isAtBottomRef: { current: true },
      sendStopIntent: () => {}, onSendFailed: () => {}, onStopUnavailable: () => {},
    })
    return { messages: messages[SID], sendMessage: stream.sendMessage }
  })
  return { view, clearAttachments }
}

const userTexts = view => view.result.current.messages.filter(m => m.role === 'user').map(m => m.text)
const sentTexts = held => held.map(h => (h.options.body instanceof FormData ? h.options.body.get('text') : JSON.parse(h.options.body).text))

describe('sends made one after another', () => {
  beforeEach(() => { apiFetch.mockReset() })

  it('a send made while the earlier one is in flight is shown at once and sent after it', async () => {
    const held = holdSends()
    const { view } = mountTab()
    let first, second, third
    act(() => { first = view.result.current.sendMessage('なんか、三回くらい') })
    await waitFor(() => expect(held).toHaveLength(1))
    act(() => { second = view.result.current.sendMessage('つづけて') })
    act(() => { third = view.result.current.sendMessage('送ると今。') })
    expect(userTexts(view)).toEqual(['なんか、三回くらい', 'つづけて', '送ると今。'])
    expect(held).toHaveLength(1)                               // the later ones wait for the earlier POST

    await act(async () => { held[0].answer(); await first })
    await waitFor(() => expect(held).toHaveLength(2))
    expect(held).toHaveLength(2)
    await act(async () => { held[1].answer(); await second })
    await waitFor(() => expect(held).toHaveLength(3))
    await act(async () => { held[2].answer(); await third })
    expect(sentTexts(held)).toEqual(['なんか、三回くらい', 'つづけて', '送ると今。'])
  })

  it('attachments an earlier send still carries are not sent again by a later one', async () => {
    const held = holdSends()
    const file = { file: { name: 'a.png' }, url: 'blob:a' }
    const { view, clearAttachments } = mountTab({ [SID]: [file] })
    let first, second
    act(() => { first = view.result.current.sendMessage('見て') })
    await waitFor(() => expect(held).toHaveLength(1))
    act(() => { second = view.result.current.sendMessage('もう一つ') })
    await act(async () => { held[0].answer(); await first })
    await waitFor(() => expect(held).toHaveLength(2))
    await act(async () => { held[1].answer(); await second })
    expect(held.map(h => h.path)).toEqual([`/pty/${SID}/send-with-files`, `/pty/${SID}/send`])
    expect(clearAttachments).toHaveBeenCalledWith(SID)
  })
})
