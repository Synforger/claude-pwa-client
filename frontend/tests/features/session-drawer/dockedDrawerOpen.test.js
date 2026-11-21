// @vitest-environment jsdom
//
// The open or shut of the tab list kept on the left: what a machine remembers, what an operation writes, and what a start
// or a window that changes size does with it (it never writes).
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { loadDockedOpen, setDrawerOpen, restoreDrawerOpen } from '../../../src/features/session-drawer/dockedDrawerOpen.js'
import { LS_DRAWER_DOCKED } from '../../../src/_common/constants.js'
import { getSnapshot as getUiSnapshot, setOverlay } from '../../../src/state/ui.js'
import { installFakeScreen, installFakeStorage, removeFakeScreen } from './fakeDockedScreen.js'

beforeEach(() => {
  installFakeStorage()
  setOverlay('drawer', false)
})
afterEach(removeFakeScreen)

const stored = () => localStorage.getItem(LS_DRAWER_DOCKED)

describe('what the machine remembers', () => {
  it('is open when nothing was ever remembered', () => {
    expect(loadDockedOpen()).toBe(true)
  })

  it('is what was written, and open again for a value that is not a boolean', () => {
    localStorage.setItem(LS_DRAWER_DOCKED, 'false')
    expect(loadDockedOpen()).toBe(false)
    localStorage.setItem(LS_DRAWER_DOCKED, 'true')
    expect(loadDockedOpen()).toBe(true)
    localStorage.setItem(LS_DRAWER_DOCKED, '{broken')
    expect(loadDockedOpen()).toBe(true)
  })
})

describe('an operation that opens or shuts the list', () => {
  it('writes what it did when the list is kept on the left', () => {
    setDrawerOpen(true, { docked: true })
    expect(getUiSnapshot().overlays.drawer).toBe(true)
    expect(stored()).toBe('true')
    setDrawerOpen(false, { docked: true })
    expect(getUiSnapshot().overlays.drawer).toBe(false)
    expect(stored()).toBe('false')
  })

  it('writes nothing when the list is laid over the screen', () => {
    setDrawerOpen(true, { docked: false })
    expect(getUiSnapshot().overlays.drawer).toBe(true)
    setDrawerOpen(false, { docked: false })
    expect(stored()).toBeNull()
  })
})

describe('a start or a window that changes size', () => {
  it('opens a wide screen that remembered nothing', () => {
    installFakeScreen(true)
    restoreDrawerOpen()
    expect(getUiSnapshot().overlays.drawer).toBe(true)
  })

  it('follows what a wide screen remembered', () => {
    installFakeScreen(true)
    localStorage.setItem(LS_DRAWER_DOCKED, 'false')
    restoreDrawerOpen()
    expect(getUiSnapshot().overlays.drawer).toBe(false)
  })

  it('shuts a narrow screen, and leaves what is remembered as it was', () => {
    installFakeScreen(false)
    setOverlay('drawer', true)
    localStorage.setItem(LS_DRAWER_DOCKED, 'true')
    restoreDrawerOpen()
    expect(getUiSnapshot().overlays.drawer).toBe(false)
    expect(stored()).toBe('true')
  })

  it('writes nothing, whichever way it goes', () => {
    const screen = installFakeScreen(true)
    restoreDrawerOpen()
    screen.set(false)
    restoreDrawerOpen()
    expect(stored()).toBeNull()
  })
})
