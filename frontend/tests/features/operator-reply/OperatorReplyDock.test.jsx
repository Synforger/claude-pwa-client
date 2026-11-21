// @vitest-environment jsdom
//
// The drawer at the top right (the bookmark): the knob, the dot for a newer answer, the open and close, and the heading.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup, fireEvent, act } from '@testing-library/react'

vi.mock('../../../src/features/chat/MessageRenderer.jsx', () => ({
  default: ({ text, streaming }) => <div data-testid="renderer" data-streaming={streaming ? '1' : '0'}>{text}</div>,
}))
vi.mock('../../../src/features/file-preview/openPath.js', () => ({ openLinkedPath: () => {} }))

import OperatorReplyDock from '../../../src/features/operator-reply/OperatorReplyDock.jsx'
import { setSessions, setActiveId } from '../../../src/state/sessions.js'
import { setMessagesFor, removeMessagesFor } from '../../../src/state/messages.js'
import { setViewMode } from '../../../src/state/ui.js'
import { AGENT_MESSAGE_OPENING, ROLLOVER_OPENING } from '../../../src/features/chat/agentMessage.js'

const store = new Map()
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => { store.set(k, String(v)) },
  removeItem: (k) => { store.delete(k) },
}

const SID = 'ses_dock'
const user = (uuid, text, ts) => ({ role: 'user', uuid, text, ts })
const agent = (uuid, text, ts, extra = {}) => ({ role: 'agent', uuid, text, tools: [], ts, ...extra })

beforeEach(() => {
  store.clear()
  setSessions([{ id: SID, agent_id: 'agent_a', title: 'Desk', created_at: 1 }])
  setActiveId(SID)
})
afterEach(() => {
  cleanup()
  act(() => { removeMessagesFor(SID); setViewMode(SID, 'chat') })
  setSessions([])
})

describe('OperatorReplyDock', () => {
  it('shows nothing while there is no answer to the operator', () => {
    act(() => setMessagesFor(SID, [user('u1', 'hello', 1000)]))
    const { queryByTestId } = render(<OperatorReplyDock />)
    expect(queryByTestId('operator-reply-knob')).toBeNull()
  })

  it('opens by the knob to the answer with the head line of the question, and closes by the knob or by a press outside', () => {
    act(() => setMessagesFor(SID, [user('u1', 'what now?\nsecond line', 1000), agent('a1', 'do this', 2000)]))
    const { getByTestId, queryByTestId } = render(<OperatorReplyDock />)
    expect(queryByTestId('operator-reply-panel')).toBeNull()
    fireEvent.click(getByTestId('operator-reply-knob'))
    expect(getByTestId('renderer').textContent).toBe('do this')
    expect(getByTestId('operator-reply-prompt').textContent).toBe('what now?')
    fireEvent.click(getByTestId('operator-reply-knob'))
    expect(queryByTestId('operator-reply-panel')).toBeNull()
    fireEvent.click(getByTestId('operator-reply-knob'))
    fireEvent.mouseDown(document.body)
    expect(queryByTestId('operator-reply-panel')).toBeNull()
  })

  it('keeps the answer while a note and its reply flow past in the chat', () => {
    const note = `${AGENT_MESSAGE_OPENING}\n<agent-message from="Desk" session="ses_x">\nlook\n</agent-message>`
    act(() => setMessagesFor(SID, [
      user('u1', 'what now?', 1000), agent('a1', 'the answer', 2000), user('u2', note, 3000), agent('a2', 'noted', 4000),
    ]))
    const { getByTestId } = render(<OperatorReplyDock />)
    fireEvent.click(getByTestId('operator-reply-knob'))
    expect(getByTestId('renderer').textContent).toBe('the answer')
  })

  it('puts a dot on the knob for an answer not opened yet, takes it away on opening, and puts it back for a newer answer', () => {
    act(() => setMessagesFor(SID, [user('u1', 'q1', 1000), agent('a1', 'first', 2000)]))
    const { getByTestId, queryByTestId } = render(<OperatorReplyDock />)
    expect(queryByTestId('operator-reply-dot')).not.toBeNull()
    fireEvent.click(getByTestId('operator-reply-knob'))
    fireEvent.click(getByTestId('operator-reply-knob'))
    expect(queryByTestId('operator-reply-dot')).toBeNull()
    act(() => setMessagesFor(SID, [user('u1', 'q1', 1000), agent('a1', 'first', 2000), user('u2', 'q2', 3000), agent('a2', 'second', 4000)]))
    expect(queryByTestId('operator-reply-dot')).not.toBeNull()
  })

  it('remembers what was opened across a reload, and still works when the storage cannot be read', () => {
    act(() => setMessagesFor(SID, [user('u1', 'q1', 1000), agent('a1', 'first', 2000)]))
    const first = render(<OperatorReplyDock />)
    fireEvent.click(first.getByTestId('operator-reply-knob'))
    first.unmount()
    expect(render(<OperatorReplyDock />).queryByTestId('operator-reply-dot')).toBeNull()
    cleanup()
    const readable = globalThis.localStorage
    globalThis.localStorage = {
      getItem: () => { throw new Error('blocked') },
      setItem: () => { throw new Error('blocked') },
      removeItem: () => {},
    }
    const blocked = render(<OperatorReplyDock />)
    expect(blocked.queryByTestId('operator-reply-dot')).not.toBeNull()
    fireEvent.click(blocked.getByTestId('operator-reply-knob'))
    expect(blocked.getByTestId('renderer').textContent).toBe('first')
    fireEvent.click(blocked.getByTestId('operator-reply-knob'))
    expect(blocked.queryByTestId('operator-reply-dot')).toBeNull()   // kept in the page for the time it lives
    globalThis.localStorage = readable
  })

  it('adds "still writing" to the heading while the turn goes on', () => {
    act(() => setMessagesFor(SID, [user('u1', 'q', 1000), agent('a1', 'half', 2000, { streaming: true })]))
    const { getByTestId } = render(<OperatorReplyDock />)
    fireEvent.click(getByTestId('operator-reply-knob'))
    expect(getByTestId('operator-reply-writing')).not.toBeNull()
    expect(getByTestId('renderer').dataset.streaming).toBe('1')
    act(() => setMessagesFor(SID, [user('u1', 'q', 1000), agent('a1', 'half and the rest', 2000)]))
    expect(getByTestId('renderer').textContent).toBe('half and the rest')
    expect(document.querySelector('[data-testid=operator-reply-writing]')).toBeNull()
  })

  it('shows the last answer before a rollover under the new session\'s report', () => {
    const start = `${ROLLOVER_OPENING}\n<session-rollover phase="start">\ntier=normal\n</session-rollover>`
    act(() => setMessagesFor(SID, [user('u1', 'fix it?', 1000), agent('a1', 'fixed in #12', 2000),
      user('u2', start, 3000), agent('a2', 'good evening, carrying on', 4000)]))
    const { getByTestId, getAllByTestId } = render(<OperatorReplyDock />)
    fireEvent.click(getByTestId('operator-reply-knob'))
    expect(getAllByTestId('renderer').map((r) => r.textContent)).toEqual(['good evening, carrying on', 'fixed in #12'])
    expect(getByTestId('operator-reply-before').textContent).toContain('fix it?')
  })

  it('is not shown over a terminal view', () => {
    act(() => { setMessagesFor(SID, [user('u1', 'q', 1000), agent('a1', 'a', 2000)]); setViewMode(SID, 'terminal') })
    const { queryByTestId } = render(<OperatorReplyDock />)
    expect(queryByTestId('operator-reply-knob')).toBeNull()
  })
})
