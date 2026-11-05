// @vitest-environment jsdom
//
// The list on screen is built from the backend's rows (`GET /sessions`, `GET /agents`), not from what the device
// remembered. A copy kept by an older build lacks the tier and the child mark; a page restored by the browser wakes
// with that copy and no way to know the backend has moved on. The tree must come out right once the backend answers,
// whether the first fetch worked, failed, or the page only came back to the front.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'

const apiFetch = vi.fn()
const reportFetch = vi.fn(() => Promise.resolve({ ok: true }))
vi.mock('../../../src/_common/api.js', () => ({ apiFetch: (...a) => apiFetch(...a) }))
vi.mock('../../../src/transport/http.ts', () => ({ httpClient: { apiFetch: (...a) => reportFetch(...a) } }))

// What an older build kept: the tabs, their fork link, and nothing the backend added later.
const OLD_COPY = [
  { id: 'ses_a', agent_id: 'agent_a', title: 'Parent', created_at: 1 },
  { id: 'ses_b', agent_id: 'agent_a', title: 'Child', created_at: 2, parent_id: 'ses_a' },
  { id: 'ses_c', agent_id: 'agent_a', title: 'Elsewhere', created_at: 3 },
]
// What the backend says now.
const SERVER_ROWS = [
  { id: 'ses_a', agent_id: 'agent_a', title: 'Parent', created_at: 1, tier: 'projects/AP', child: false, parent_id: null },
  { id: 'ses_b', agent_id: 'agent_a', title: 'Child', created_at: 2, tier: 'projects/AP', child: true, parent_id: 'ses_a' },
  { id: 'ses_c', agent_id: 'agent_a', title: 'Elsewhere', created_at: 3, tier: 'projects/Harbor', child: false, parent_id: null },
]
const AGENTS = [{ id: 'agent_a', display_name: 'Agent A' }]

// Node's own `localStorage` global has no methods without a file; the page's is a plain key-value store.
function makeLocalStorage() {
  let store = {}
  return {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v) },
    removeItem: (k) => { delete store[k] },
    clear: () => { store = {} },
  }
}

const answer = (value) => Promise.resolve({ ok: true, json: () => Promise.resolve(value) })

// Serves what `routes` maps each path to; a path set to null fails the way a request fails while the network is
// not back yet.
function serve(routes) {
  apiFetch.mockImplementation((path) => {
    const body = routes[path]
    return body === null ? Promise.reject(new Error('Load failed')) : answer(body)
  })
}

// A fresh module state per test: the list's state lives in module variables, as it does in a page that just started.
async function startPage({ remembered = OLD_COPY } = {}) {
  vi.resetModules()
  vi.stubGlobal('localStorage', makeLocalStorage())
  if (remembered) localStorage.setItem('cpc_sessions_meta', JSON.stringify(remembered))
  const sessions = await import('../../../src/state/sessions.js')
  const hook = await import('../../../src/features/session-drawer/useSessions.js')
  const tree = await import('../../../src/features/session-drawer/folderTree.js')
  return { sessions, hook, tree }
}

const folderNames = (tree, sessions) => tree
  .folderTree(sessions.getSnapshot().sessions, { agents: sessions.getSnapshot().agents })
  .filter(row => row.kind === 'folder').map(row => row.name)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('the list after the page wakes with a copy an older build kept', () => {
  it('starts as the copy: flat, with no child mark', async () => {
    const { sessions, tree } = await startPage()
    expect(sessions.getSnapshot().sessions.every(s => s.tier === undefined && s.child === undefined)).toBe(true)
    expect(folderNames(tree, sessions)).toEqual([])
  })

  it('becomes the backend\'s rows, and the tree comes out, once the backend answers', async () => {
    serve({ '/sessions': SERVER_ROWS, '/agents': AGENTS })
    const { sessions, hook, tree } = await startPage()
    await hook.refetchFromBackend()
    const rows = sessions.getSnapshot().sessions
    expect(rows.find(s => s.id === 'ses_b')).toMatchObject({ tier: 'projects/AP', child: true })
    expect(sessions.getSnapshot().agents).toEqual(AGENTS)
    expect(folderNames(tree, sessions)).toEqual(['AP', 'Harbor'])
  })

  it('takes the rows of the backend even when its set of tabs is the same as the copy\'s', async () => {
    // The overview snapshot only says which tabs exist; with the same ids it never asks for the rows.
    serve({ '/sessions': SERVER_ROWS, '/agents': AGENTS })
    const { sessions, hook } = await startPage()
    await hook.reconcileSessionIds(['ses_a', 'ses_b', 'ses_c'])
    expect(sessions.getSnapshot().sessions.find(s => s.id === 'ses_b').child).toBe(true)
  })

  it('does not ask again for the same ids once the backend has answered', async () => {
    serve({ '/sessions': SERVER_ROWS, '/agents': AGENTS })
    const { hook } = await startPage()
    await hook.reconcileSessionIds(['ses_a', 'ses_b', 'ses_c'])
    apiFetch.mockClear()
    await hook.reconcileSessionIds(['ses_a', 'ses_b', 'ses_c'])
    expect(apiFetch).not.toHaveBeenCalled()
  })
})

describe('when the first fetch fails (= the network is not back yet as the page wakes)', () => {
  it('keeps the copy on screen and asks again at the next snapshot, even with the same ids', async () => {
    serve({ '/sessions': null, '/agents': null })
    const { sessions, hook } = await startPage()
    await hook.refetchFromBackend()
    expect(sessions.getSnapshot().sessions).toEqual(OLD_COPY)
    expect(hook.hasServerRows()).toBe(false)

    serve({ '/sessions': SERVER_ROWS, '/agents': AGENTS })
    await hook.reconcileSessionIds(['ses_a', 'ses_b', 'ses_c'])
    expect(hook.hasServerRows()).toBe(true)
    expect(sessions.getSnapshot().sessions.find(s => s.id === 'ses_c').tier).toBe('projects/Harbor')
  })

  it('takes the agents even when the list failed, and the list even when the agents failed', async () => {
    serve({ '/sessions': null, '/agents': AGENTS })
    const { sessions, hook } = await startPage()
    await hook.refetchFromBackend()
    expect(sessions.getSnapshot().agents).toEqual(AGENTS)
    expect(hook.hasServerRows()).toBe(false)

    serve({ '/sessions': SERVER_ROWS, '/agents': null })
    await hook.refetchFromBackend()
    expect(hook.hasServerRows()).toBe(true)
    expect(sessions.getSnapshot().agents).toEqual(AGENTS)
  })

  it('asks one request at a time: a second call waits for the one in flight', async () => {
    serve({ '/sessions': SERVER_ROWS, '/agents': AGENTS })
    const { hook } = await startPage()
    await Promise.all([hook.refetchFromBackend(), hook.refetchFromBackend()])
    expect(apiFetch.mock.calls.filter(([path]) => path === '/sessions')).toHaveLength(1)
  })
})

describe('when the page comes back to the front', () => {
  it('reports the rows it woke with, then takes the backend\'s rows', async () => {
    serve({ '/sessions': SERVER_ROWS, '/agents': AGENTS })
    const { sessions, hook } = await startPage()
    renderHook(() => hook.useSessions())
    await vi.waitFor(() => expect(hook.hasServerRows()).toBe(true))
    // The page is frozen with a stale list: the rows go back to what an older build kept.
    sessions.setSessions(OLD_COPY)
    reportFetch.mockClear()
    apiFetch.mockClear()

    window.dispatchEvent(new Event('cpc:fg'))

    const [path, init] = reportFetch.mock.calls[0]
    expect(path).toBe('/log/sw')
    expect(init.jsonBody).toMatchObject({
      stage: 'drawer:tree', trigger: 'foreground', sessionCount: 3, withTierCount: 0, childCount: 0, serverAnswered: true,
    })
    await vi.waitFor(() => expect(sessions.getSnapshot().sessions.find(s => s.id === 'ses_b').child).toBe(true))
  })
})
