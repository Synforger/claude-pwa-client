import { describe, it, expect, vi, beforeEach } from 'vitest'

// Pinning a tab shows at once, like the notification setting, and is sent to the backend through the same door as the
// tab's name and notifications. A pin the backend did not take is taken back.

const apiFetch = vi.fn()
const patchSession = vi.fn()
let rows = []

vi.mock('../../../src/_common/api.js', () => ({ apiFetch: (...a) => apiFetch(...a) }))
vi.mock('../../../src/state/sessions.js', () => ({
  appendSession: vi.fn(),
  patchSession: (...a) => patchSession(...a),
  setActiveId: vi.fn(),
  getSnapshot: () => ({ sessions: rows, activeId: null }),
  removeSession: vi.fn(),
  subscribe: vi.fn(),
  setSessions: vi.fn(),
  clearUnreadDone: vi.fn(),
}))

describe('setAccountPinned', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    rows = [{ id: 'ses_tab', account_pinned: false }]
  })

  it('shows the pin at once and sends only the pin to the tab\'s own route', async () => {
    const { setAccountPinned } = await import('../../../src/features/session-drawer/useSessions.js')
    apiFetch.mockResolvedValue({ ok: true })
    await setAccountPinned('ses_tab', true)
    expect(patchSession).toHaveBeenCalledTimes(1)
    expect(patchSession).toHaveBeenCalledWith('ses_tab', { account_pinned: true })
    const [url, opts] = apiFetch.mock.calls[0]
    expect(url).toBe('/sessions/ses_tab')
    expect(opts.method).toBe('PATCH')
    expect(JSON.parse(opts.body)).toEqual({ account_pinned: true })
  })

  it('sends the pin going, too', async () => {
    const { setAccountPinned } = await import('../../../src/features/session-drawer/useSessions.js')
    rows = [{ id: 'ses_tab', account_pinned: true }]
    apiFetch.mockResolvedValue({ ok: true })
    await setAccountPinned('ses_tab', false)
    expect(patchSession).toHaveBeenCalledWith('ses_tab', { account_pinned: false })
    expect(JSON.parse(apiFetch.mock.calls[0][1].body)).toEqual({ account_pinned: false })
  })

  it('takes the pin back when the backend refuses it or cannot be reached', async () => {
    const { setAccountPinned } = await import('../../../src/features/session-drawer/useSessions.js')
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    apiFetch.mockResolvedValueOnce({ ok: false, status: 400 })
    await setAccountPinned('ses_tab', true)
    expect(patchSession.mock.calls.map((c) => c[1].account_pinned)).toEqual([true, false])
    patchSession.mockClear()
    apiFetch.mockRejectedValueOnce(new Error('offline'))
    await setAccountPinned('ses_tab', true)
    expect(patchSession.mock.calls.map((c) => c[1].account_pinned)).toEqual([true, false])
  })
})
