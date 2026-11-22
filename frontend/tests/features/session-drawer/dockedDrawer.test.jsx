// @vitest-environment jsdom
//
// The tab list on a wide screen with a mouse stays on the left: no curtain, it stays after a tab, the tickets or the settings
// are opened, and only its ✕ (and the ☰ of the top bar) shut it. On a narrow screen it is laid over the screen as it was:
// a curtain, and it shuts after each of those. The window that changes size is followed.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup, fireEvent, act, waitFor } from '@testing-library/react'

vi.mock('../../../src/_common/api.js', () => ({
  apiFetch: (path) => Promise.resolve({
    ok: true,
    json: () => Promise.resolve(path === '/accounts' ? [{ id: 'personal', display_name: 'Personal', is_default: true }] : []),
  }),
}))

import SessionDrawer from '../../../src/features/session-drawer/SessionDrawer.jsx'
import { useDockedDrawerRestore } from '../../../src/features/session-drawer/useDockedDrawer.js'
import { setSessions, setActiveId, getSnapshot as getSessionsSnapshot } from '../../../src/state/sessions.js'
import { getSnapshot as getUiSnapshot, setOverlay } from '../../../src/state/ui.js'
import { applyTicketsSnapshot } from '../../../src/state/tickets.js'
import { LS_DRAWER_DOCKED } from '../../../src/_common/constants.js'
import { installFakeScreen, installFakeStorage, removeFakeScreen } from './fakeDockedScreen.js'

const DESK = { id: 'ses_desk', agent_id: 'agent_a', title: 'Desk', created_at: 2, account_id: 'personal' }
const OTHER = { id: 'ses_other', agent_id: 'agent_a', title: 'Other', created_at: 1, account_id: 'personal' }
const HELD = { id: 't1', title: 'T1', status: 'open', holder: 'ses_desk', attention: null, marks: [] }

const drawerOpen = () => getUiSnapshot().overlays.drawer
const stored = () => localStorage.getItem(LS_DRAWER_DOCKED)

function mount(wide) {
  const screen = installFakeScreen(wide)
  setOverlay('drawer', true)
  const view = render(<SessionDrawer />)
  return { screen, ...view }
}

beforeEach(() => {
  installFakeStorage()
  setSessions([DESK, OTHER])
  setActiveId('ses_desk')
  act(() => applyTicketsSnapshot({ tickets: [HELD], peers: {} }))
})
afterEach(() => {
  cleanup()
  setOverlay('drawer', false)
  setOverlay('tickets', false)
  setOverlay('ticket', null)
  setOverlay('settings', false)
  setSessions([])
  act(() => applyTicketsSnapshot({ tickets: [], peers: {} }))
  removeFakeScreen()
})

describe('the tab list kept on the left (a wide screen with a mouse)', () => {
  it('is marked docked and has no curtain', () => {
    const { getByTestId, container } = mount(true)
    expect(getByTestId('session-drawer').className).toContain('docked')
    expect(container.querySelector('.drawer-overlay')).toBeNull()
  })

  it('stays open after a tab is chosen, and the tab is the active one', () => {
    const { getAllByTestId } = mount(true)
    fireEvent.click(getAllByTestId('session-list-item-select')[1])
    expect(getSessionsSnapshot().activeId).not.toBe('ses_desk')
    expect(drawerOpen()).toBe(true)
  })

  it('has the tickets on its first row, and no mark of a ticket on a tab', () => {
    const { getByTestId, container } = mount(true)
    expect(container.querySelector('.drawer-list').firstElementChild).toBe(getByTestId('drawer-tickets-open'))
    expect(container.textContent.split('🎫')).toHaveLength(2)   // the row's, and no other
    expect(container.textContent).not.toContain(HELD.title)
  })

  it('counts on that row the tickets of all tabs that want a look, and no number while none does', () => {
    const { getByTestId } = mount(true)
    const count = () => getByTestId('drawer-tickets-open').querySelector('.drawer-item-hidden')
    expect(count()).toBeNull()
    act(() => applyTicketsSnapshot({ tickets: [
      HELD, { ...HELD, id: 't2', attention: 'waiting' }, { ...HELD, id: 't3', holder: 'ses_other', marks: ['overdue'] },
    ], peers: {} }))
    expect(count().textContent).toBe('2')
  })

  it('has that row also when there is no tab', () => {
    setSessions([])
    expect(mount(true).getByTestId('drawer-tickets-open')).toBeTruthy()
  })

  it('stays open after the list of tickets or the settings is opened', () => {
    const { getByTestId } = mount(true)
    fireEvent.click(getByTestId('drawer-tickets-open'))
    expect(getUiSnapshot().overlays.tickets).toBe(true)
    fireEvent.click(getByTestId('drawer-settings'))
    fireEvent.click(getByTestId('open-settings'))
    expect(getUiSnapshot().overlays.settings).toBe(true)
    expect(drawerOpen()).toBe(true)
  })

  it('is shut by its ✕, and the machine remembers it', () => {
    const { getByTestId } = mount(true)
    fireEvent.click(getByTestId('drawer-close'))
    expect(drawerOpen()).toBe(false)
    expect(stored()).toBe('false')
  })
})

describe('the tab list laid over the screen (a narrow screen, or a touch screen)', () => {
  it('has a curtain, and is not marked docked', () => {
    const { getByTestId, container } = mount(false)
    expect(getByTestId('session-drawer').className).not.toContain('docked')
    expect(container.querySelector('.drawer-overlay')).not.toBeNull()
  })

  it('shuts after a tab is chosen', () => {
    const { getAllByTestId } = mount(false)
    fireEvent.click(getAllByTestId('session-list-item-select')[1])
    expect(drawerOpen()).toBe(false)
  })

  it('shuts after the tickets or the settings are opened', () => {
    for (const open of [
      (view) => fireEvent.click(view.getByTestId('drawer-tickets-open')),
      (view) => { fireEvent.click(view.getByTestId('drawer-settings')); fireEvent.click(view.getByTestId('open-settings')) },
    ]) {
      const view = mount(false)
      open(view)
      expect(drawerOpen()).toBe(false)
      cleanup()
    }
  })

  it('shuts by the curtain or by its ✕, and remembers neither', () => {
    const first = mount(false)
    fireEvent.click(first.container.querySelector('.drawer-overlay'))
    expect(drawerOpen()).toBe(false)
    cleanup()
    const second = mount(false)
    fireEvent.click(second.getByTestId('drawer-close'))
    expect(drawerOpen()).toBe(false)
    expect(stored()).toBeNull()
  })
})

describe('the window that changes size', () => {
  function Restorer() {
    useDockedDrawerRestore()
    return null
  }

  it('shuts the list when the screen gets narrow, opens it by what was remembered when it gets wide, and writes nothing', async () => {
    const { screen, getByTestId, container } = mount(true)
    render(<Restorer />)
    expect(drawerOpen()).toBe(true)

    act(() => screen.set(false))
    expect(drawerOpen()).toBe(false)
    expect(stored()).toBeNull()

    act(() => screen.set(true))
    await waitFor(() => expect(drawerOpen()).toBe(true))

    fireEvent.click(getByTestId('drawer-close'))
    expect(stored()).toBe('false')
    act(() => screen.set(false))
    act(() => screen.set(true))
    expect(drawerOpen()).toBe(false)
    expect(container.querySelector('.drawer-overlay')).toBeNull()
  })
})
