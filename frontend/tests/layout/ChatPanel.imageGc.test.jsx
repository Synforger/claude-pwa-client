// @vitest-environment jsdom
//
// The GC of attached images that the panel runs once, a few seconds after it starts, deletes the images no message
// holds. An image that sits in the attachment bar and is not sent yet is held by no message, but it is not an orphan:
// it must be kept, or the image is gone from IndexedDB (and its URL revoked) before it is sent. The parts that read the
// backend are replaced; what is checked is the set of image ids the panel hands to the GC.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'

const SID = 'ses_claude'
const held = { messages: {}, attachments: {} }
const gcImages = vi.fn()

vi.mock('../../src/features/session-drawer/useSessions.js', async () => {
  const sessions = await import('../../src/state/sessions.js')
  return { useSessions: () => ({ sessions: sessions.getSnapshot().sessions, setActiveId: () => {}, forkSession: () => {} }) }
})
vi.mock('../../src/features/session-drawer/useSessionsOverview.js', () => ({ useSessionsOverview: () => {} }))
vi.mock('../../src/features/session-drawer/useSessionActivity.js', () => ({ useSessionActivity: () => {} }))
vi.mock('../../src/features/session-drawer/useViewsWs.js', () => ({ useViewsWs: () => ({ sendStopIntent: () => {} }) }))
vi.mock('../../src/features/chat/useChatStorage.js', () => ({
  useChatStorage: () => ({ messages: held.messages, setMessages: () => {}, input: {}, setInput: () => {} }),
}))
vi.mock('../../src/features/chat/useAutoScroll.js', () => ({
  useAutoScroll: () => ({ scrollerDomRef: { current: null }, isAtBottomRef: { current: true }, showScrollBtn: false,
    hasNew: false, scrollToBottom: () => {}, onScroll: () => {} }),
}))
vi.mock('../../src/features/chat/useChatStream.js', () => ({
  useChatStream: () => ({ loading: {}, setLoading: () => {}, sendMessage: () => {}, fetchLatest: () => {}, optimisticRef: { current: {} } }),
}))
vi.mock('../../src/features/attachments/useAttachments.js', () => ({
  useAttachments: () => ({ attachments: held.attachments, fileInputRef: { current: null }, handleFileSelect: () => {},
    removeAttachment: () => {}, clearAttachments: () => {} }),
}))
vi.mock('../../src/features/attachments/imageStore.js', () => ({ gcImages: (...args) => gcImages(...args) }))
vi.mock('../../src/features/status-bar/useStatus.js', () => ({ useStatus: () => ({}) }))
vi.mock('../../src/features/push-notify/useSessionBadges.js', () => ({
  useSessionBadges: () => ({ unreadCount: 0, onOverviewPayload: () => {} }),
}))
vi.mock('../../src/features/push-notify/badge.js', () => ({ setBadge: () => {} }))
vi.mock('../../src/features/chat/useRunningSubagents.js', () => ({ useRunningSubagents: () => new Set() }))
vi.mock('../../src/features/tasks/ActivityBar.jsx', () => ({ default: () => null }))
vi.mock('../../src/features/status-bar/PromptStateBanner.jsx', () => ({ PromptStateBanner: () => null }))
vi.mock('../../src/features/chat/ChatInput.jsx', () => ({ default: () => <div data-testid="chat-input" /> }))
vi.mock('../../src/features/chat/MessageList.jsx', () => ({ default: () => <div data-testid="message-list" /> }))
vi.mock('../../src/features/chat/AttachmentsBar.jsx', () => ({ default: () => <div data-testid="attachments-bar" /> }))
vi.mock('../../src/features/plan-approval/PlanApprovalBubble.jsx', () => ({ default: () => <div data-testid="plan-bubble" /> }))
vi.mock('../../src/features/extensions/useExtensions.js', () => ({ usePageExtensionOpen: () => false }))
vi.mock('../../src/features/voice/index.js', () => ({ setVoiceSender: () => {}, adoptAppCall: () => {} }))
vi.mock('../../src/features/file-preview/openPath.js', () => ({ openLinkedPath: () => {} }))

import ChatPanel from '../../src/layout/ChatPanel.jsx'
import { setSessions } from '../../src/state/sessions.js'

const STARTUP_GC_MS = 5000

beforeEach(() => {
  vi.useFakeTimers()
  gcImages.mockReset().mockResolvedValue(0)
  held.messages = {}
  held.attachments = {}
  setSessions([{ id: SID, agent_id: 'agent_a', title: 'Desk', created_at: 2 }])
})
afterEach(() => {
  cleanup()
  setSessions([])
  vi.useRealTimers()
})

describe('the startup GC of attached images', () => {
  it('hands the GC the images of the messages and the images waiting in the attachment bar', () => {
    held.messages = { [SID]: [{ id: 'm1', role: 'user', text: 'hi', imageRefs: ['sent1', 'sent2'] }, { id: 'm2', role: 'agent', text: 'ok' }] }
    held.attachments = { [SID]: [{ file: {}, url: 'blob:x', imageId: 'waiting' }, { file: {}, url: null, imageId: null }] }

    render(<ChatPanel sid={SID} />)
    expect(gcImages).not.toHaveBeenCalled()
    vi.advanceTimersByTime(STARTUP_GC_MS)

    expect(gcImages).toHaveBeenCalledTimes(1)
    expect([...gcImages.mock.calls[0][0]].sort()).toEqual(['sent1', 'sent2', 'waiting'])
  })

  it('hands it just the messages\' images when nothing waits in the bar', () => {
    held.messages = { [SID]: [{ id: 'm1', role: 'user', text: 'hi', imageRefs: ['sent1'] }] }

    render(<ChatPanel sid={SID} />)
    vi.advanceTimersByTime(STARTUP_GC_MS)

    expect([...gcImages.mock.calls[0][0]]).toEqual(['sent1'])
  })
})
