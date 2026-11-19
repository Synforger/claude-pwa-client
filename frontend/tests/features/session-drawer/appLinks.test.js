// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from 'vitest'
import { listenAppLinks } from '../../../src/features/session-drawer/appLinks.js'

// ブラウザか、 app の中か、 を作り分ける。
function device({ native = false } = {}) {
  window.Capacitor = native
    ? { isNativePlatform: () => true, isPluginAvailable: (name) => name === 'AppLink', Plugins: { AppLink: native } }
    : undefined
}

afterEach(() => {
  delete window.Capacitor
})

describe('listenAppLinks', () => {
  it('opens the tab the app was opened with, and removes the listener', async () => {
    const remove = vi.fn()
    const fired = {}
    const plugin = { addListener: vi.fn((name, fn) => { fired[name] = fn; return Promise.resolve({ remove }) }) }
    const fire = (...args) => fired.openSession(...args)
    device({ native: plugin })
    const onOpen = vi.fn()
    const stop = listenAppLinks(onOpen)
    expect(plugin.addListener).toHaveBeenCalledWith('openSession', expect.any(Function))
    fire({ sid: 'ses_a' })
    fire({})
    fire({ sid: 'ses_b', call: true })
    expect(onOpen).toHaveBeenCalledTimes(2)
    expect(onOpen).toHaveBeenNthCalledWith(1, 'ses_a', { call: false })
    expect(onOpen).toHaveBeenNthCalledWith(2, 'ses_b', { call: true })
    stop()
    await Promise.resolve()
    await Promise.resolve()
    expect(remove).toHaveBeenCalledTimes(2)
  })

  it('opens the ticket the app was opened with, and ignores an empty one', () => {
    const fired = {}
    device({ native: { addListener: vi.fn((name, fn) => { fired[name] = fn; return Promise.resolve({ remove: vi.fn() }) }) } })
    const onOpenTicket = vi.fn()
    listenAppLinks(vi.fn(), onOpenTicket)
    fired.openTicket({ ticket: 'home-261119-01' })
    fired.openTicket({})
    expect(onOpenTicket).toHaveBeenCalledTimes(1)
    expect(onOpenTicket).toHaveBeenCalledWith('home-261119-01')
  })

  it('does nothing in a browser, or in an app built before AppLink', () => {
    device()
    expect(listenAppLinks(vi.fn())).toBeTypeOf('function')
    window.Capacitor = { isNativePlatform: () => true, isPluginAvailable: () => false, Plugins: {} }
    expect(listenAppLinks(vi.fn())).toBeTypeOf('function')
  })
})
