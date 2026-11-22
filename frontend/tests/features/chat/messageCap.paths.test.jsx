// @vitest-environment jsdom
//
// A conversation holds at most MAX_MESSAGES messages in memory, whichever path adds to it. Each path below runs
// against the real setter `useChatStorage` hands out, from a list that is already full: a streamed assistant frame, a
// system card, a question, a message of the user from the stream, a message the user sends, and the end of a session.
// Before the cut was moved to the setter, the first, the third, the fifth and the sixth did not cut at all.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'

const apiFetch = vi.fn()
vi.mock('../../../src/_common/api.js', () => ({ apiFetch: (...args) => apiFetch(...args) }))
vi.mock('../../../src/transport/select.ts', () => ({
  chatTransport: {
    subscribe: () => () => {},
    setSubscribedSids: vi.fn(),
    setVoiceSids: vi.fn(),
    getOffset: () => null,
    getConfirmed: () => null,
    confirmHistory: vi.fn(),
    forgetConfirmed: vi.fn(),
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

import '../../../src/features/chat/index.js'          // registers the kinds of system cards
import '../../../src/features/tasks/index.js'
import { MAX_MESSAGES } from '../../../src/_common/constants.js'
import { useChatStorage } from '../../../src/features/chat/useChatStorage.js'
import { useStreamBuffer } from '../../../src/features/chat/useStreamBuffer.js'
import { useChatStream } from '../../../src/features/chat/useChatStream.js'
import { processStreamEvent } from '../../../src/features/chat/processStreamEvent.js'
import { reconcileUserMessage } from '../../../src/features/chat/reconcileUserMessage.js'

const SID = 'ses_cap'
const SESSIONS = [{ id: SID }]
const ROUNDS = 30

function mountFullTab() {
  const view = renderHook(() => {
    const storage = useChatStorage(SESSIONS)
    const buffer = useStreamBuffer({ setMessages: storage.setMessages })
    const stream = useChatStream({
      activeSession: { id: SID },
      setMessages: storage.setMessages,
      input: {}, setInput: () => {},
      attachments: {}, clearAttachments: () => {},
      scrollToBottom: () => {}, isAtBottomRef: { current: true },
      sendStopIntent: () => {}, onSendFailed: () => {}, onStopUnavailable: () => {},
    })
    return { storage, buffer, stream }
  })
  const full = Array.from({ length: MAX_MESSAGES }, (_, i) => ({ id: `old${i}`, uuid: `old${i}`, role: 'agent', text: `old ${i}`, ts: 1000 + i }))
  act(() => { view.result.current.storage.setMessages(() => ({ [SID]: full })) })
  return view
}

const list = view => view.result.current.storage.messages[SID]
const streamDeps = view => {
  const { storage, buffer } = view.result.current
  return { setMessages: storage.setMessages, cancelAndFlush: buffer.cancelAndFlush, scheduleFlush: buffer.scheduleFlush, bufFor: buffer.bufFor }
}

describe('a full conversation stays at MAX_MESSAGES through every path that adds to it', () => {
  beforeEach(() => { apiFetch.mockReset(); apiFetch.mockResolvedValue({ ok: true, json: async () => ({ ok: true }) }) })

  it('mounts full', () => {
    expect(list(mountFullTab())).toHaveLength(MAX_MESSAGES)
  })

  it('streamed assistant frames', () => {
    const view = mountFullTab()
    for (let i = 0; i < ROUNDS; i++) {
      act(() => {
        processStreamEvent(streamDeps(view), SID, { type: 'assistant', uuid: `msg_${i}`, ts: 5000 + i, message: { content: [{ type: 'text', text: `frame ${i}` }] } })
        view.result.current.buffer.cancelAndFlush(SID)
      })
    }
    expect(list(view)).toHaveLength(MAX_MESSAGES)
    expect(list(view).at(-1).text).toBe(`frame ${ROUNDS - 1}`)
    expect(list(view).some(m => m.id === 'old0')).toBe(false)      // the oldest went
  })

  it('system cards', () => {
    const view = mountFullTab()
    for (let i = 0; i < ROUNDS; i++) {
      act(() => { processStreamEvent(streamDeps(view), SID, { type: 'system_note', uuid: `note_${i}`, ts: 5000 + i, note: 'x' }) })
    }
    expect(list(view)).toHaveLength(MAX_MESSAGES)
    expect(list(view).filter(m => m.kind === 'system_note')).toHaveLength(ROUNDS)
  })

  it('questions', () => {
    const view = mountFullTab()
    for (let i = 0; i < ROUNDS; i++) {
      act(() => { processStreamEvent(streamDeps(view), SID, { type: 'ask_user_question', tool_use_id: `toolu_${i}`, input: { questions: [{ question: 'Q?', options: [{ label: 'A' }] }] } }) })
    }
    expect(list(view)).toHaveLength(MAX_MESSAGES)
    expect(list(view).filter(m => m.askUserQuestion).length).toBeGreaterThan(0)
  })

  it("the user's messages from the stream", () => {
    const view = mountFullTab()
    for (let i = 0; i < ROUNDS; i++) {
      act(() => {
        view.result.current.storage.setMessages(prev => ({ ...prev, [SID]: reconcileUserMessage(prev[SID] || [], `said ${i}`, `uu${i}`, undefined, 5000 + i) }))
      })
    }
    expect(list(view)).toHaveLength(MAX_MESSAGES)
    expect(list(view).at(-1).text).toBe(`said ${ROUNDS - 1}`)
  })

  it('messages the user sends (the bubble and the empty reply that wait for the stream)', async () => {
    const view = mountFullTab()
    for (let i = 0; i < ROUNDS; i++) {
      await act(async () => { await view.result.current.stream.sendMessage(`send ${i}`) })
    }
    expect(list(view)).toHaveLength(MAX_MESSAGES)
    expect(list(view).filter(m => m.role === 'user' && m.text?.startsWith('send ')).length).toBeGreaterThan(0)
  })

  it('the end of a session', async () => {
    const view = mountFullTab()
    for (let i = 0; i < ROUNDS; i++) {
      await act(async () => { await view.result.current.stream.endSession() })
    }
    expect(list(view)).toHaveLength(MAX_MESSAGES)
    expect(list(view).at(-1).kind).toBe('session_end')
  })
})
