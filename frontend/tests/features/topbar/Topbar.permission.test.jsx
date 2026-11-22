// @vitest-environment jsdom
//
// The top bar's 🔐 button: it stands beside 📑 only while the tab's status carries a permission window, only in the
// chat view of a Claude tab, and opens the window's dialog through the overlay.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup, fireEvent } from '@testing-library/react'

const mockStatus = vi.fn()
vi.mock('../../../src/features/status-bar/useStatus.js', () => ({ useStatus: (...a) => mockStatus(...a) }))
vi.mock('../../../src/features/screenshare/useMoonlightAvailable.js', () => ({ useMoonlightAvailable: () => false }))
vi.mock('../../../src/features/extensions/ExtensionMenu.jsx', () => ({ default: () => null }))

import Topbar from '../../../src/features/topbar/Topbar.jsx'
import { setSessions, setActiveId } from '../../../src/state/sessions.js'
import { getSnapshot as getUiSnapshot, setOverlay, setViewMode } from '../../../src/state/ui.js'

const CLAUDE = { id: 'ses_claude', agent_id: 'agent_a', title: 'Desk', created_at: 2 }
const API = { id: 'api_support-bot', agent_id: 'agent_a', title: 'Support bot', created_at: 0, kind: 'api' }
const WINDOW = { number: 1, tool_name: 'Bash', input: { command: 'ls' }, record_input: null, index: 1, count: 1 }

beforeEach(() => {
  setSessions([CLAUDE, API])
  setActiveId('ses_claude')
})
afterEach(() => {
  cleanup()
  setSessions([])
  setOverlay('permissionOpen', false)
  setViewMode('ses_claude', 'chat')
  mockStatus.mockReset()
})

describe('Topbar 🔐', () => {
  it('shows while a window is open and goes when it is not', () => {
    mockStatus.mockReturnValue({ pending_permission: WINDOW })
    const open = render(<Topbar />)
    expect(open.queryByTestId('permission-window-open-button')).not.toBeNull()
    cleanup()
    mockStatus.mockReturnValue({ pending_permission: null })
    expect(render(<Topbar />).queryByTestId('permission-window-open-button')).toBeNull()
    cleanup()
    mockStatus.mockReturnValue(null)
    expect(render(<Topbar />).queryByTestId('permission-window-open-button')).toBeNull()
  })

  it('stands right after 📑 when both wait', () => {
    mockStatus.mockReturnValue({ pending_plan: { plan: 'x' }, pending_permission: WINDOW })
    const { getByTestId } = render(<Topbar />)
    expect(getByTestId('plan-approval-open-button').nextElementSibling).toBe(getByTestId('permission-window-open-button'))
  })

  it('is not offered on an API tab or in the terminal view', () => {
    mockStatus.mockReturnValue({ pending_permission: WINDOW })
    setActiveId('api_support-bot')
    expect(render(<Topbar />).queryByTestId('permission-window-open-button')).toBeNull()
    cleanup()
    setActiveId('ses_claude')
    setViewMode('ses_claude', 'terminal')
    expect(render(<Topbar />).queryByTestId('permission-window-open-button')).toBeNull()
  })

  it('opens the dialog through the overlay', () => {
    mockStatus.mockReturnValue({ pending_permission: WINDOW })
    const { getByTestId } = render(<Topbar />)
    fireEvent.click(getByTestId('permission-window-open-button'))
    expect(getUiSnapshot().overlays.permissionOpen).toBe(true)
  })
})
