// @vitest-environment jsdom
//
// The ☰ of the top bar: on a wide screen with a mouse the tab list stays on the left, so ☰ opens it and shuts it
// (and the machine remembers which); on any other screen it only opens the list laid over the screen, as it always did.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup, fireEvent, act } from '@testing-library/react'

vi.mock('../../../src/features/status-bar/useStatus.js', () => ({ useStatus: () => ({}) }))
vi.mock('../../../src/features/screenshare/useMoonlightAvailable.js', () => ({ useMoonlightAvailable: () => false }))
vi.mock('../../../src/features/extensions/ExtensionMenu.jsx', () => ({ default: () => null }))

import Topbar from '../../../src/features/topbar/Topbar.jsx'
import { setSessions, setActiveId } from '../../../src/state/sessions.js'
import { getSnapshot as getUiSnapshot, setOverlay } from '../../../src/state/ui.js'
import { LS_DRAWER_DOCKED } from '../../../src/_common/constants.js'
import { installFakeScreen, installFakeStorage, removeFakeScreen } from '../session-drawer/fakeDockedScreen.js'

const drawerOpen = () => getUiSnapshot().overlays.drawer
const stored = () => localStorage.getItem(LS_DRAWER_DOCKED)

beforeEach(() => {
  installFakeStorage()
  setSessions([{ id: 'ses_desk', agent_id: 'agent_a', title: 'Desk', created_at: 1 }])
  setActiveId('ses_desk')
  setOverlay('drawer', false)
})
afterEach(() => {
  cleanup()
  setOverlay('drawer', false)
  setSessions([])
  removeFakeScreen()
})

describe('☰ on a wide screen with a mouse', () => {
  it('opens the list, then shuts it, and remembers each', () => {
    installFakeScreen(true)
    const { getByTestId } = render(<Topbar />)
    fireEvent.click(getByTestId('drawer-toggle'))
    expect(drawerOpen()).toBe(true)
    expect(stored()).toBe('true')
    fireEvent.click(getByTestId('drawer-toggle'))
    expect(drawerOpen()).toBe(false)
    expect(stored()).toBe('false')
  })

  it('shuts a list that was open from the start', () => {
    installFakeScreen(true)
    setOverlay('drawer', true)
    const { getByTestId } = render(<Topbar />)
    fireEvent.click(getByTestId('drawer-toggle'))
    expect(drawerOpen()).toBe(false)
  })

  it('follows the window: a screen that turns narrow makes ☰ open the list again, without writing', () => {
    const screen = installFakeScreen(true)
    const { getByTestId } = render(<Topbar />)
    act(() => screen.set(false))
    fireEvent.click(getByTestId('drawer-toggle'))
    fireEvent.click(getByTestId('drawer-toggle'))
    expect(drawerOpen()).toBe(true)
    expect(stored()).toBeNull()
  })
})

describe('☰ on any other screen', () => {
  it('only opens the list, and remembers nothing', () => {
    installFakeScreen(false)
    const { getByTestId } = render(<Topbar />)
    fireEvent.click(getByTestId('drawer-toggle'))
    expect(drawerOpen()).toBe(true)
    fireEvent.click(getByTestId('drawer-toggle'))
    expect(drawerOpen()).toBe(true)
    expect(stored()).toBeNull()
  })
})
