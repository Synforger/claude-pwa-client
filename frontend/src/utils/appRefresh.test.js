// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { hardRefreshAppShell, REFRESH_PREPARE_TIMEOUT_MS } from './appRefresh.js'

let replace

beforeEach(() => {
  vi.useFakeTimers()
  replace = vi.fn()
  // jsdom の location は差し替えられないので、 読み込み直しの呼び出しだけ受ける物に替える
  vi.stubGlobal('location', { href: 'http://app.test/?ses=abc', replace })
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function stubServiceWorker(registration) {
  vi.stubGlobal('navigator', { serviceWorker: { getRegistrations: () => Promise.resolve([registration]) } })
}

describe('hardRefreshAppShell', () => {
  it('clears the caches, waits for the new service worker, then reloads with a cache-busting query', async () => {
    const deleted = []
    vi.stubGlobal('caches', { keys: () => Promise.resolve(['shell-a', 'shell-b']), delete: (k) => { deleted.push(k); return Promise.resolve(true) } })
    const incoming = { state: 'installing', addEventListener: (_t, fn) => { incoming.onstate = fn } }
    const registration = { update: vi.fn(() => Promise.resolve()), installing: incoming, waiting: null }
    stubServiceWorker(registration)

    const done = hardRefreshAppShell()
    await vi.advanceTimersByTimeAsync(10)
    expect(deleted).toEqual(['shell-a', 'shell-b'])
    expect(registration.update).toHaveBeenCalledTimes(1)
    expect(replace).not.toHaveBeenCalled() // 新しい service worker が有効になるのを待っている

    incoming.state = 'activated'
    incoming.onstate()
    await done
    expect(replace).toHaveBeenCalledTimes(1)
    const url = new URL(replace.mock.calls[0][0])
    expect(url.searchParams.get('ses')).toBe('abc')
    expect(url.searchParams.get('_r')).toBeTruthy()
  })

  it('still reloads when the update check never comes back', async () => {
    vi.stubGlobal('caches', { keys: () => Promise.resolve([]), delete: () => Promise.resolve(true) })
    stubServiceWorker({ update: () => new Promise(() => {}), installing: null, waiting: null })

    const done = hardRefreshAppShell()
    await vi.advanceTimersByTimeAsync(REFRESH_PREPARE_TIMEOUT_MS - 1)
    expect(replace).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    await done
    expect(replace).toHaveBeenCalledTimes(1)
  })

  it('still reloads when the cache storage never answers', async () => {
    vi.stubGlobal('caches', { keys: () => new Promise(() => {}), delete: () => Promise.resolve(true) })
    stubServiceWorker({ update: () => Promise.resolve(), installing: null, waiting: null })

    const done = hardRefreshAppShell()
    await vi.advanceTimersByTimeAsync(REFRESH_PREPARE_TIMEOUT_MS)
    await done
    expect(replace).toHaveBeenCalledTimes(1)
  })

  it('still reloads when a new service worker never becomes active', async () => {
    vi.stubGlobal('caches', { keys: () => Promise.resolve([]), delete: () => Promise.resolve(true) })
    stubServiceWorker({ update: () => Promise.resolve(), installing: { state: 'installing', addEventListener: () => {} }, waiting: null })

    const done = hardRefreshAppShell()
    await vi.advanceTimersByTimeAsync(REFRESH_PREPARE_TIMEOUT_MS)
    await done
    expect(replace).toHaveBeenCalledTimes(1)
  })

  it('reloads at once when there is nothing to prepare', async () => {
    vi.stubGlobal('caches', { keys: () => Promise.resolve([]), delete: () => Promise.resolve(true) })
    vi.stubGlobal('navigator', {})
    await hardRefreshAppShell()
    expect(replace).toHaveBeenCalledTimes(1)
  })
})
