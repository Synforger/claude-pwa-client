// @vitest-environment jsdom
//
// 票の一覧: 3 段 (閉じたは畳む)、 行は題・求める物・持つタブ・経過、 一番下にもう 1 台の数。
import { it, expect, afterEach, beforeEach, vi } from 'vitest'
import { render, cleanup, fireEvent, screen, act } from '@testing-library/react'
import TicketDrawer from '../../../src/features/tickets/TicketDrawer.jsx'
import { applyTicketsSnapshot } from '../../../src/state/tickets.js'
import { setOverlay } from '../../../src/state/ui.js'
import * as sessions from '../../../src/state/sessions.js'

const row = (id, extra = {}) => ({
  id, title: `T ${id}`, status: 'open', wants: null, holder: 'ses_a', attention: null,
  last_at: new Date(Date.now() - 5 * 60_000).toISOString(), opened_at: null, ...extra,
})

beforeEach(() => {
  vi.spyOn(sessions, 'getSnapshot').mockReturnValue({ activeId: 'ses_a', sessions: [{ id: 'ses_a', title: 'client work' }] })
})

afterEach(() => {
  act(() => { setOverlay('tickets', false); setOverlay('ticket', null); applyTicketsSnapshot({ tickets: [], peers: {} }) })
  cleanup()
  vi.restoreAllMocks()
})

it('sorts the tickets into the groups, shows what each asks and who holds it, and folds the closed ones', () => {
  act(() => applyTicketsSnapshot({
    tickets: [
      row('home-1', { status: 'waiting-operator', wants: 'decide', attention: 'waiting' }),
      row('home-2'),
      row('home-3', { holder: '' , attention: 'no_holder' }),
      row('home-4', { holder: 'company:ses_x' }),
      row('home-5', { status: 'closed' }),
    ],
    peers: {},
  }))
  render(<TicketDrawer />)
  const attention = screen.getByTestId('ticket-group-attention')
  expect(attention.textContent).toContain('T home-1')
  expect(attention.textContent).toContain('Decide')
  expect(attention.textContent).toContain('client work')
  expect(attention.textContent).toContain('No tab holds it')
  expect(screen.getByTestId('ticket-group-running').textContent).toContain('A tab on company')
  expect(screen.getByTestId('ticket-group-running').textContent).toContain('5 min ago')
  const closed = screen.getByTestId('ticket-group-closed')
  expect(closed.textContent).not.toContain('T home-5')
  fireEvent.click(screen.getByTestId('ticket-group-toggle'))
  expect(closed.textContent).toContain('T home-5')
})

it('opens the ticket screen by the row', () => {
  act(() => applyTicketsSnapshot({ tickets: [row('home-1')], peers: {} }))
  render(<TicketDrawer />)
  fireEvent.click(screen.getByTestId('ticket-row'))
  // the ticket's id is what the ticket overlay now holds
  return import('../../../src/state/ui.js').then(({ getSnapshot }) => expect(getSnapshot().overlays.ticket).toBe('home-1'))
})

it('says how many tickets the other machine has waiting, and that a machine that does not answer cannot be read', () => {
  act(() => applyTicketsSnapshot({ tickets: [], peers: { company: { waiting: 2 }, away: { unreadable: true } } }))
  render(<TicketDrawer />)
  const lines = screen.getAllByTestId('ticket-peer').map((el) => el.textContent)
  expect(lines).toEqual(['away: cannot be read', 'Answer on the screen of company: 2 (tickets outside every boundary only)'])
})

it('says there is no ticket once the first picture came and it is empty', () => {
  act(() => applyTicketsSnapshot({ tickets: [], peers: {} }))
  render(<TicketDrawer />)
  expect(screen.getByText('No tickets')).toBeTruthy()
})
