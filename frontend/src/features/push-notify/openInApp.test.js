// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from 'vitest'
import { listenAppLinks } from './openInApp.js'

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
    let fire
    const plugin = { addListener: vi.fn((name, fn) => { fire = fn; return Promise.resolve({ remove }) }) }
    device({ native: plugin })
    const onOpen = vi.fn()
    const stop = listenAppLinks(onOpen)
    expect(plugin.addListener).toHaveBeenCalledWith('openSession', expect.any(Function))
    fire({ sid: 'ses_a' })
    fire({})
    expect(onOpen).toHaveBeenCalledTimes(1)
    expect(onOpen).toHaveBeenCalledWith('ses_a')
    stop()
    await Promise.resolve()
    await Promise.resolve()
    expect(remove).toHaveBeenCalledTimes(1)
  })

  it('does nothing in a browser, or in an app built before AppLink', () => {
    device()
    expect(listenAppLinks(vi.fn())).toBeTypeOf('function')
    window.Capacitor = { isNativePlatform: () => true, isPluginAvailable: () => false, Plugins: {} }
    expect(listenAppLinks(vi.fn())).toBeTypeOf('function')
  })
})
