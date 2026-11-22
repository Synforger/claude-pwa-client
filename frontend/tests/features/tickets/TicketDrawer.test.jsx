// @vitest-environment jsdom
//
// 票の一覧: 上に今のタブ、 下にほかをタブごと、 最後に閉じた (畳む)。 行は題・求める物・持つタブ・経過・期限・印の 1 字、 一番下にもう 1 台の数。
import { it, expect, afterEach, beforeEach, vi } from 'vitest'
import { render, cleanup, fireEvent, screen, act } from '@testing-library/react'
import TicketDrawer from '../../../src/features/tickets/TicketDrawer.jsx'
import { applyTicketsSnapshot } from '../../../src/state/tickets.js'
import { setOverlay } from '../../../src/state/ui.js'
import * as sessions from '../../../src/state/sessions.js'

const row = (id, extra = {}) => ({
  id, title: `T ${id}`, status: 'open', wants: null, holder: 'ses_a', attention: null,
  last_at: new Date(Date.now() - 5 * 60_000).toISOString(), opened_at: null, origin: 'self', due: null, marks: [], next: '', ...extra,
})

beforeEach(() => {
  vi.spyOn(sessions, 'getSnapshot').mockReturnValue({ activeId: 'ses_a', unreadDone: {}, sessions: [{ id: 'ses_a', title: 'client work' }, { id: 'ses_b', title: 'notes' }] })
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
  const own = screen.getByTestId('ticket-section-own')
  expect(own.querySelector('[data-testid=ticket-group-attention]').textContent).toContain('T home-1')
  expect(own.textContent).toContain('Decide')
  expect(own.querySelector('[data-testid=ticket-group-running]').textContent).toContain('5 min ago')
  const others = screen.getByTestId('ticket-section-others')
  expect(others.textContent).toContain('No tab holds it')
  expect(others.textContent).toContain('A tab on company')
  expect(screen.queryByTestId('ticket-holder-open')).toBeNull()   // neither is a tab of this machine to go to
  const closed = screen.getByTestId('ticket-group-closed')
  expect(closed.textContent).not.toContain('T home-5')
  fireEvent.click(screen.getByTestId('ticket-group-toggle'))
  expect(closed.textContent).toContain('T home-5')
  expect(closed.textContent).toContain('client work')
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
  expect(lines).toEqual(['away: cannot be read', 'Tickets waiting for an answer on company: 2 (answer on the screen of company)'])
})

it('shows no line for a machine that has no ticket waiting', () => {
  act(() => applyTicketsSnapshot({ tickets: [], peers: { company: { waiting: 0 } } }))
  render(<TicketDrawer />)
  expect(screen.queryAllByTestId('ticket-peer')).toEqual([])
})

it('counts in the title of the closed group only the closed tickets it shows', () => {
  const longAgo = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString()
  act(() => applyTicketsSnapshot({
    tickets: [row('home-1', { status: 'closed' }), row('home-2', { status: 'closed', last_at: longAgo })],
    peers: {},
  }))
  render(<TicketDrawer />)
  expect(screen.getByTestId('ticket-group-toggle').textContent).toContain('(1)')
  fireEvent.click(screen.getByTestId('ticket-group-toggle'))
  expect(screen.getByTestId('ticket-group-closed').textContent).toContain('T home-1')
  expect(screen.getByTestId('ticket-group-closed').textContent).not.toContain('T home-2')
})

it('says there is no ticket once the first picture came and it is empty', () => {
  act(() => applyTicketsSnapshot({ tickets: [], peers: {} }))
  render(<TicketDrawer />)
  expect(screen.getByText('No tickets')).toBeTruthy()
})

it('shows the waiting group between the running and the closed one, and does not fold it', () => {
  act(() => applyTicketsSnapshot({
    tickets: [row('home-1'), row('home-2', { status: 'waiting' }), row('home-3', { status: 'closed' })],
    peers: {},
  }))
  render(<TicketDrawer />)
  const order = screen.getAllByTestId(/^ticket-group-(attention|running|waiting|closed)$/).map((el) => el.dataset.testid)
  expect(order).toEqual(['ticket-group-running', 'ticket-group-waiting', 'ticket-group-closed'])
  const waiting = screen.getByTestId('ticket-group-waiting')
  expect(waiting.textContent).toContain('Waiting (1)')
  expect(waiting.textContent).toContain('T home-2')
  expect(screen.getByTestId('ticket-group-running').textContent).not.toContain('T home-2')
})

it('shows the due date of a row, and the first mark as one character with its name', () => {
  act(() => applyTicketsSnapshot({
    tickets: [
      row('home-1', { due: '2026-11-18', marks: ['overdue', 'idle'] }),
      row('home-2', { status: 'waiting', marks: ['waiting_stale'] }),
      row('home-3', { due: '2026-11-30' }),
    ],
    peers: {},
  }))
  render(<TicketDrawer />)
  const rowOf = (id) => document.querySelector(`[data-ticket="${id}"]`)
  const overdue = rowOf('home-1')
  expect(overdue.querySelector('[data-testid=ticket-row-mark]').textContent).toBe('⚠\uFE0F')
  expect(overdue.querySelector('[data-testid=ticket-row-mark]').getAttribute('aria-label')).toBe('Overdue')
  expect(overdue.querySelectorAll('[data-testid=ticket-row-mark]')).toHaveLength(1)
  expect(overdue.querySelector('[data-testid=ticket-row-due]').textContent).toBe('Due 2026-11-18')
  expect(rowOf('home-2').querySelector('[data-testid=ticket-row-mark]').textContent).toBe('💤')
  expect(rowOf('home-2').querySelector('[data-testid=ticket-row-due]')).toBeNull()
  expect(rowOf('home-3').querySelector('[data-testid=ticket-row-mark]')).toBeNull()
  expect(rowOf('home-3').querySelector('[data-testid=ticket-row-due]').textContent).toBe('Due 2026-11-30')
})

it('draws a row of an older backend, with none of the new fields, without a mark or a due date', () => {
  const old = row('home-1')
  for (const field of ['origin', 'due', 'marks', 'next']) delete old[field]
  act(() => applyTicketsSnapshot({ tickets: [old], peers: {} }))
  render(<TicketDrawer />)
  expect(screen.getByTestId('ticket-row').textContent).toContain('T home-1')
  expect(screen.queryByTestId('ticket-row-mark')).toBeNull()
  expect(screen.queryByTestId('ticket-row-due')).toBeNull()
  expect(screen.queryByTestId('ticket-row-next')).toBeNull()
})

it('shows the next step its tab wrote under the title of a row, and nothing under a row that has none', () => {
  act(() => applyTicketsSnapshot({
    tickets: [row('home-1', { next: 'Waiting for the sample deck' }), row('home-2', { next: '' })],
    peers: {},
  }))
  render(<TicketDrawer />)
  const rowOf = (id) => document.querySelector(`[data-ticket="${id}"]`)
  const next = rowOf('home-1').querySelector('[data-testid=ticket-row-next]')
  expect(next.textContent).toBe('Waiting for the sample deck')
  expect(next.previousElementSibling.className).toContain('ticket-row-title')
  expect(rowOf('home-2').querySelector('[data-testid=ticket-row-next]')).toBeNull()
})

it('draws the next step as plain text, never as markup', () => {
  act(() => applyTicketsSnapshot({ tickets: [row('home-1', { next: 'Fix <b>it</b>' })], peers: {} }))
  render(<TicketDrawer />)
  const next = screen.getByTestId('ticket-row-next')
  expect(next.textContent).toBe('Fix <b>it</b>')
  expect(next.querySelector('b')).toBeNull()
})

it('puts this tab first and the others by tab, each ticket once, and goes to a tab by its heading', () => {
  const select = vi.spyOn(sessions, 'selectTab').mockImplementation(() => {})
  act(() => {
    applyTicketsSnapshot({ tickets: [row('home-1'), row('home-2', { holder: 'ses_b' })], peers: { company: { waiting: 2 } } })
    setOverlay('tickets', true)
  })
  render(<TicketDrawer />)
  expect(screen.getAllByTestId('ticket-row').map((r) => r.dataset.ticket)).toEqual(['home-1', 'home-2'])
  expect(screen.getByTestId('ticket-section-own').textContent).toContain('T home-1')
  expect(screen.getByTestId('ticket-section-others').textContent).not.toContain('T home-1')
  expect(screen.getByTestId('ticket-peer')).toBeTruthy()
  fireEvent.click(screen.getByTestId('ticket-holder-open'))
  expect(select).toHaveBeenCalledWith('ses_b')
  return import('../../../src/state/ui.js').then(({ getSnapshot }) => expect(getSnapshot().overlays.tickets).toBe(false))
})
