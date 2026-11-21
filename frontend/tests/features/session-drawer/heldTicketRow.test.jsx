// @vitest-environment jsdom
//
// The line under a tab in the conversation list that names the tickets the tab holds: a waiting ticket gets a pause sign
// before its title, a ticket with a mark gets the mark's one character, and a ticket that moves with no mark stays as it was.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup, waitFor, act } from '@testing-library/react'

vi.mock('../../../src/_common/api.js', () => ({
  apiFetch: (path) => Promise.resolve({
    ok: true,
    json: () => Promise.resolve(path === '/accounts' ? [{ id: 'personal', display_name: 'Personal', is_default: true }] : []),
  }),
}))

import SessionDrawer from '../../../src/features/session-drawer/SessionDrawer.jsx'
import { setSessions, setActiveId } from '../../../src/state/sessions.js'
import { setOverlay } from '../../../src/state/ui.js'
import { applyTicketsSnapshot } from '../../../src/state/tickets.js'

const TAB = { id: 'ses_desk', agent_id: 'agent_a', title: 'Desk', created_at: 1, account_id: 'personal' }
const row = (id, extra = {}) => ({ id, title: `T ${id}`, status: 'open', holder: 'ses_desk', attention: null, marks: [], ...extra })

beforeEach(() => {
  setSessions([TAB])
  setActiveId('ses_desk')
  setOverlay('drawer', true)
})
afterEach(() => {
  cleanup()
  setSessions([])
  act(() => applyTicketsSnapshot({ tickets: [], peers: {} }))
})

async function heldLine(tickets) {
  act(() => applyTicketsSnapshot({ tickets, peers: {} }))
  const { findByTestId } = render(<SessionDrawer />)
  return (await findByTestId('session-held-ticket')).textContent
}

describe('the held tickets line of a tab', () => {
  it('is the pin and the title for a ticket that moves and has no mark', async () => {
    expect(await heldLine([row('a')])).toBe('📌 T a')
  })

  it('puts the pause sign before the title of a waiting ticket', async () => {
    expect(await heldLine([row('a', { status: 'waiting' })])).toBe('📌 ⏸ T a')
  })

  it('puts the first mark as one character before the title', async () => {
    expect(await heldLine([row('a', { marks: ['overdue', 'idle'] })])).toBe('📌 ⚠\uFE0F T a')
  })

  it('puts the mark of a ticket that is due soon the same way', async () => {
    expect(await heldLine([row('b', { marks: ['due_soon'] })])).toBe('📌 ⏰ T b')
  })

  it('marks each ticket on its own when the tab holds several', async () => {
    expect(await heldLine([row('a', { status: 'waiting', marks: ['waiting_stale'] }), row('b')])).toBe('📌 ⏸ 💤 T a / T b')
  })

  it('shows no line for a closed ticket', async () => {
    act(() => applyTicketsSnapshot({ tickets: [row('a', { status: 'closed' })], peers: {} }))
    const { container } = render(<SessionDrawer />)
    await waitFor(() => expect(container.querySelector('[data-cpc-sid="ses_desk"]')).not.toBeNull())
    expect(container.querySelector('[data-testid="session-held-ticket"]')).toBeNull()
  })
})
