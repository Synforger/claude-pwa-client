import { describe, it, expect, vi, beforeEach } from 'vitest'

// Switching a tab's account keeps the same tab: the client sends only the account, and patches the row with what
// the backend returns (no tab is added, the view stays on the tab). A fork sends the message it branches from.

const apiFetch = vi.fn()
const appendSession = vi.fn()
const patchSession = vi.fn()
const setActiveId = vi.fn()

vi.mock('../../_common/api.js', () => ({ apiFetch: (...a) => apiFetch(...a) }))
vi.mock('../../state/sessions.js', () => ({
  appendSession: (...a) => appendSession(...a),
  patchSession: (...a) => patchSession(...a),
  setActiveId: (...a) => setActiveId(...a),
  getSnapshot: () => ({ sessions: [], activeId: null }),
  removeSession: vi.fn(),
  subscribe: vi.fn(),
  setSessions: vi.fn(),
  clearUnreadDone: vi.fn(),
}))

function okResponse(meta) {
  return Promise.resolve({ ok: true, json: () => Promise.resolve(meta) })
}

describe('moveToAccount', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('sends only the account to the tab\'s own account route', async () => {
    const { moveToAccount } = await import('./useSessions.js')
    apiFetch.mockReturnValue(okResponse({ id: 'ses_tab', account_id: 'work' }))
    await moveToAccount('ses_tab', 'work')
    expect(apiFetch).toHaveBeenCalledTimes(1)
    const [url, opts] = apiFetch.mock.calls[0]
    expect(url).toBe('/sessions/ses_tab/account')
    expect(JSON.parse(opts.body)).toEqual({ account_id: 'work' })
  })

  it('patches the same row and adds no tab', async () => {
    const { moveToAccount } = await import('./useSessions.js')
    const meta = { id: 'ses_tab', title: 'Chat', account_id: 'work' }
    apiFetch.mockReturnValue(okResponse(meta))
    const out = await moveToAccount('ses_tab', 'work')
    expect(out).toBe(meta)
    expect(patchSession).toHaveBeenCalledWith('ses_tab', meta)
    expect(appendSession).not.toHaveBeenCalled()
    expect(setActiveId).not.toHaveBeenCalled()
  })

  it('a fork sends the message it branches from', async () => {
    const { forkSession } = await import('./useSessions.js')
    apiFetch.mockReturnValue(okResponse({ id: 'ses_new' }))
    await forkSession('ses_src', 'uuid-1')
    expect(JSON.parse(apiFetch.mock.calls[0][1].body)).toEqual({ from_uuid: 'uuid-1' })
  })
})
