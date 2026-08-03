import { describe, it, expect, vi, beforeEach } from 'vitest'

// アカウントを移して続ける経路は、 分岐位置をユーザに選ばせない (= 欲しいのは常に「今の続き」)。
// backend が末尾から最初の安全な切れ目を採るので、 client は from_uuid を送らない。

const apiFetch = vi.fn()
const appendSession = vi.fn()
const setActiveId = vi.fn()

vi.mock('../../utils/api.js', () => ({ apiFetch: (...a) => apiFetch(...a) }))
vi.mock('../../state/sessions.js', () => ({
  appendSession: (...a) => appendSession(...a),
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

describe('continueOnAccount', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('from_uuid を送らず、 移し先アカウントだけを送る', async () => {
    const { continueOnAccount } = await import('./useSessions.js')
    apiFetch.mockReturnValue(okResponse({ id: 'ses_new', account_id: 'work' }))
    await continueOnAccount('ses_src', 'work')
    expect(apiFetch).toHaveBeenCalledTimes(1)
    const [url, opts] = apiFetch.mock.calls[0]
    expect(url).toBe('/sessions/ses_src/fork')
    expect(JSON.parse(opts.body)).toEqual({ target_account_id: 'work' })
  })

  it('返ってきた新タブを一覧に挿して表示を移す', async () => {
    const { continueOnAccount } = await import('./useSessions.js')
    const meta = { id: 'ses_new', account_id: 'work' }
    apiFetch.mockReturnValue(okResponse(meta))
    const out = await continueOnAccount('ses_src', 'work')
    expect(out).toBe(meta)
    expect(appendSession).toHaveBeenCalledWith(meta)
    expect(setActiveId).toHaveBeenCalledWith('ses_new')
  })

  it('位置を指定した通常の分岐では from_uuid を送る', async () => {
    const { forkSession } = await import('./useSessions.js')
    apiFetch.mockReturnValue(okResponse({ id: 'ses_new' }))
    await forkSession('ses_src', 'uuid-1')
    expect(JSON.parse(apiFetch.mock.calls[0][1].body)).toEqual({ from_uuid: 'uuid-1' })
  })
})
