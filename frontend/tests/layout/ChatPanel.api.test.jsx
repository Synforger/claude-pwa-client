// @vitest-environment jsdom
//
// The conversation of an API tab (no Claude Code behind it) is drawn as any other, but the place of the input holds one
// line saying it is only shown, and nothing that needs a Claude Code is offered: no input, no stop, no attachment, no
// fork, no sub-agents, no plan approval, no permission window. A Claude tab's panel keeps its input. The parts that read the backend are
// replaced; what is checked is which parts the panel mounts.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'

const seen = { messageList: null, activityStatus: undefined, bannerSid: undefined }

vi.mock('../../src/features/session-drawer/useSessions.js', async () => {
  const sessions = await import('../../src/state/sessions.js')
  return { useSessions: () => ({ sessions: sessions.getSnapshot().sessions, setActiveId: () => {}, forkSession: () => {} }) }
})
vi.mock('../../src/features/session-drawer/useSessionsOverview.js', () => ({ useSessionsOverview: () => {} }))
vi.mock('../../src/features/session-drawer/useSessionActivity.js', () => ({ useSessionActivity: () => {} }))
vi.mock('../../src/features/session-drawer/useViewsWs.js', () => ({ useViewsWs: () => ({ sendStopIntent: () => {} }) }))
vi.mock('../../src/features/chat/useChatStorage.js', () => ({
  useChatStorage: () => ({ messages: {}, setMessages: () => {}, input: {}, setInput: () => {} }),
}))
vi.mock('../../src/features/chat/useAutoScroll.js', () => ({
  useAutoScroll: () => ({ scrollerDomRef: { current: null }, isAtBottomRef: { current: true }, showScrollBtn: false,
    hasNew: false, scrollToBottom: () => {}, onScroll: () => {} }),
}))
vi.mock('../../src/features/chat/useChatStream.js', () => ({
  useChatStream: () => ({ loading: {}, setLoading: () => {}, sendMessage: () => {}, fetchLatest: () => {}, optimisticRef: { current: {} } }),
}))
vi.mock('../../src/features/attachments/useAttachments.js', () => ({
  useAttachments: () => ({ attachments: {}, fileInputRef: { current: null }, handleFileSelect: () => {},
    removeAttachment: () => {}, clearAttachments: () => {} }),
}))
vi.mock('../../src/features/attachments/imageStore.js', () => ({ gcImages: () => Promise.resolve() }))
vi.mock('../../src/features/status-bar/useStatus.js', () => ({ useStatus: () => ({ pending_plan: { plan: 'x' }, pending_permission: { number: 1 } }) }))
vi.mock('../../src/features/push-notify/useSessionBadges.js', () => ({
  useSessionBadges: () => ({ unreadCount: 0, onOverviewPayload: () => {} }),
}))
vi.mock('../../src/features/push-notify/badge.js', () => ({ setBadge: () => {} }))
vi.mock('../../src/features/tasks/ActivityBar.jsx', () => ({
  default: ({ status }) => { seen.activityStatus = status; return null },
}))
vi.mock('../../src/features/status-bar/PromptStateBanner.jsx', () => ({
  PromptStateBanner: ({ sid }) => { seen.bannerSid = sid; return null },
}))
vi.mock('../../src/features/chat/ChatInput.jsx', () => ({ default: () => <div data-testid="chat-input" /> }))
vi.mock('../../src/features/chat/MessageList.jsx', () => ({
  default: (props) => { seen.messageList = props; return <div data-testid="message-list" /> },
}))
vi.mock('../../src/features/chat/AttachmentsBar.jsx', () => ({ default: () => <div data-testid="attachments-bar" /> }))
vi.mock('../../src/features/plan-approval/PlanApprovalBubble.jsx', () => ({ default: () => <div data-testid="plan-bubble" /> }))
vi.mock('../../src/features/permission-window/PermissionWindowDialog.jsx', () => ({
  default: ({ sid }) => <div data-testid="permission-dialog" data-sid={sid} />,
}))
vi.mock('../../src/features/extensions/useExtensions.js', () => ({ usePageExtensionOpen: () => false }))
vi.mock('../../src/features/voice/index.js', () => ({ setVoiceSender: () => {}, adoptAppCall: () => {} }))
vi.mock('../../src/features/file-preview/openPath.js', () => ({ openLinkedPath: () => {} }))

import ChatPanel from '../../src/layout/ChatPanel.jsx'
import { setSessions } from '../../src/state/sessions.js'
import { setOverlay } from '../../src/state/ui.js'

const CLAUDE = { id: 'ses_claude', agent_id: 'agent_a', title: 'Desk', created_at: 2 }
const API = { id: 'api_support-bot', agent_id: 'agent_a', title: 'Support bot', created_at: 0, kind: 'api' }

beforeEach(() => {
  setSessions([CLAUDE, API])
  setOverlay('planOpen', true)
  setOverlay('permissionOpen', true)
  Object.assign(seen, { messageList: null, activityStatus: undefined, bannerSid: undefined })
})
afterEach(() => {
  cleanup()
  setSessions([])
  setOverlay('planOpen', false)
  setOverlay('permissionOpen', false)
})

describe('ChatPanel of an API tab', () => {
  it('draws the conversation and puts one line where the input would be', () => {
    const { queryByTestId } = render(<ChatPanel sid="api_support-bot" />)
    expect(queryByTestId('message-list')).not.toBeNull()
    expect(queryByTestId('api-tab-readonly')).not.toBeNull()
    expect(queryByTestId('api-tab-readonly').textContent).not.toBe('')
    expect(queryByTestId('api-tab-readonly').textContent).not.toMatch(/^chat\./)      // a real wording, not the key
  })

  it('offers no input, no stop, no attachment, no plan approval, no permission window', () => {
    const { queryByTestId } = render(<ChatPanel sid="api_support-bot" />)
    expect(queryByTestId('chat-input')).toBeNull()
    expect(queryByTestId('plan-bubble')).toBeNull()
    expect(queryByTestId('permission-dialog')).toBeNull()
    expect(document.querySelector('input[type="file"]')).toBeNull()
  })

  it('gives the conversation no fork, and asks nothing of a Claude Code (prompt state, activity)', () => {
    render(<ChatPanel sid="api_support-bot" />)
    expect(seen.messageList.onFork).toBeNull()
    expect(seen.bannerSid).toBeNull()
    expect(seen.activityStatus).toBeNull()
  })
})

describe('ChatPanel of a Claude tab', () => {
  it('mounts the permission window of its own tab when one is open', () => {
    const { getByTestId } = render(<ChatPanel sid="ses_claude" />)
    expect(getByTestId('permission-dialog').getAttribute('data-sid')).toBe('ses_claude')
  })

  it('keeps the input and its fork, and shows no line about API tabs', () => {
    const { queryByTestId } = render(<ChatPanel sid="ses_claude" />)
    expect(queryByTestId('chat-input')).not.toBeNull()
    expect(queryByTestId('api-tab-readonly')).toBeNull()
    expect(typeof seen.messageList.onFork).toBe('function')
    expect(seen.bannerSid).toBe('ses_claude')
  })
})
