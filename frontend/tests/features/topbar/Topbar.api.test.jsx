// @vitest-environment jsdom
//
// The top bar of an API tab (no Claude Code behind it): no notes, no plan approval. A Claude tab's bar keeps them.
// The top bar has no robot; 🎫 stands beside ⭐ with the tickets that want a look (this tab / all).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup, fireEvent, act } from '@testing-library/react'

const mockStatus = vi.fn()
vi.mock('../../../src/features/status-bar/useStatus.js', () => ({ useStatus: (...a) => mockStatus(...a) }))
vi.mock('../../../src/features/screenshare/useMoonlightAvailable.js', () => ({ useMoonlightAvailable: () => false }))
vi.mock('../../../src/features/extensions/ExtensionMenu.jsx', () => ({ default: () => null }))

import Topbar from '../../../src/features/topbar/Topbar.jsx'
import { setSessions, setActiveId } from '../../../src/state/sessions.js'
import { applyTicketsSnapshot } from '../../../src/state/tickets.js'
import { getSnapshot as getUiSnapshot, setOverlay } from '../../../src/state/ui.js'

const CLAUDE = { id: 'ses_claude', agent_id: 'agent_a', title: 'Desk', created_at: 2 }
const API = { id: 'api_support-bot', agent_id: 'agent_a', title: 'Support bot', created_at: 0, kind: 'api' }

beforeEach(() => {
  setSessions([CLAUDE, API])
  mockStatus.mockReturnValue({ pending_plan: { plan: 'x' } })
})
afterEach(() => {
  cleanup()
  setSessions([])
  mockStatus.mockReset()
})

describe('Topbar', () => {
  it('shows the notes and plan-approval buttons of a Claude tab, 🎫, and no robot', () => {
    setActiveId('ses_claude')
    const { queryByTestId } = render(<Topbar />)
    expect(queryByTestId('notes-open-button')).not.toBeNull()
    expect(queryByTestId('plan-approval-open-button')).not.toBeNull()
    expect(queryByTestId('tickets-open-button')).not.toBeNull()
    expect(queryByTestId('subagents-open-button')).toBeNull()
  })

  it('shows none of them for an API tab, and still its name', () => {
    setActiveId('api_support-bot')
    const { queryByTestId, container } = render(<Topbar />)
    expect(queryByTestId('notes-open-button')).toBeNull()
    expect(queryByTestId('plan-approval-open-button')).toBeNull()
    expect(container.querySelector('.topbar-title').textContent).toBe('Support bot')
  })
})


describe('Topbar tickets', () => {
  const row = (id, attention) => ({ id, title: id, status: 'open', holder: 'ses_claude', opener: 'ses_claude', attention })

  afterEach(() => {
    act(() => { applyTicketsSnapshot({ tickets: [], peers: {} }); setOverlay('drawer', false) })
  })

  it('shows no number on 🎫 while no ticket wants a look', () => {
    setActiveId('ses_claude')
    act(() => applyTicketsSnapshot({ tickets: [row('a', null)], peers: {} }))
    const { queryByTestId } = render(<Topbar />)
    expect(queryByTestId('tickets-count')).toBeNull()
  })

  it('shows on 🎫, beside ⭐, how many want a look of this tab and of all', () => {
    setActiveId('api_support-bot')
    act(() => applyTicketsSnapshot({ tickets: [row('a', 'waiting'), row('b', 'delivery'), row('c', null)], peers: {} }))
    const { getByTestId } = render(<Topbar />)
    expect(getByTestId('tickets-count').textContent).toBe('0 / 2')
    expect(getByTestId('favorites-open-button').nextElementSibling).toBe(getByTestId('tickets-open-button'))
    expect(getByTestId('drawer-toggle').textContent).toBe('☰')
    act(() => setActiveId('ses_claude'))
    expect(getByTestId('tickets-count').textContent).toBe('2 / 2')
  })

  it('opens the list of tickets', () => {
    setActiveId('ses_claude')
    const { getByTestId } = render(<Topbar />)
    fireEvent.click(getByTestId('tickets-open-button'))
    expect(getUiSnapshot().overlays.tickets).toBe(true)
    act(() => setOverlay('tickets', false))
  })

  it('stays, with the number of all, when no tab is open', () => {
    setSessions([])
    setActiveId(null)
    act(() => applyTicketsSnapshot({ tickets: [row('a', 'waiting')], peers: {} }))
    const { getByTestId, queryByTestId } = render(<Topbar />)
    expect(queryByTestId('favorites-open-button')).toBeNull()
    expect(getByTestId('tickets-count').textContent).toBe('1')
  })

  it('opens the tab list by the menu button, number or not', () => {
    setActiveId('ses_claude')
    act(() => applyTicketsSnapshot({ tickets: [row('a', 'waiting')], peers: {} }))
    const { getByTestId } = render(<Topbar />)
    fireEvent.click(getByTestId('drawer-toggle'))
    expect(getUiSnapshot().overlays.drawer).toBe(true)
  })

  it('takes the number away when the last ticket that wanted a look is settled', () => {
    setActiveId('ses_claude')
    act(() => applyTicketsSnapshot({ tickets: [row('a', 'waiting')], peers: {} }))
    const { queryByTestId } = render(<Topbar />)
    expect(queryByTestId('tickets-count')).not.toBeNull()
    act(() => applyTicketsSnapshot({ tickets: [row('a', null)], peers: {} }))
    expect(queryByTestId('tickets-count')).toBeNull()
  })
})
