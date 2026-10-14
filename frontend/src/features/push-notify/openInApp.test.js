// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  appLink,
  listenAppLinks,
  openFromNotification,
  openInAppAvailable,
  setOpenInAppEnabled,
} from './openInApp.js'

const IPHONE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148'
const MAC_UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15'

let location

// iPhone のホーム画面の PWA か、 Mac のブラウザか、 app の中か、 を作り分ける。
function device({ ua = IPHONE_UA, standalone = true, platform = 'iPhone', touch = 5, native = false } = {}) {
  vi.stubGlobal('navigator', { userAgent: ua, standalone, platform, maxTouchPoints: touch })
  location = { href: 'https://host.example/' }
  vi.stubGlobal('location', location)
  window.Capacitor = native
    ? { isNativePlatform: () => true, isPluginAvailable: (name) => name === 'AppLink', Plugins: { AppLink: native } }
    : undefined
}

beforeEach(() => {
  const store = new Map()
  vi.stubGlobal('localStorage', {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => { store.set(k, String(v)) },
    removeItem: (k) => { store.delete(k) },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  delete window.Capacitor
})

describe('openInAppAvailable', () => {
  it('is offered only in the home-screen PWA on an iPhone', () => {
    device()
    expect(openInAppAvailable()).toBe(true)
    device({ standalone: false })
    expect(openInAppAvailable()).toBe(false) // Safari のタブ
    device({ ua: MAC_UA, standalone: false, platform: 'MacIntel', touch: 0 })
    expect(openInAppAvailable()).toBe(false) // デスクトップ
    device({ native: { addListener: vi.fn() } })
    expect(openInAppAvailable()).toBe(false) // app の中 (= 渡す先が自分)
  })
})

describe('openFromNotification', () => {
  it('switches the tab and stays in the PWA while the switch is off', () => {
    device()
    const setActiveId = vi.fn()
    openFromNotification('ses_a', setActiveId)
    expect(setActiveId).toHaveBeenCalledWith('ses_a')
    expect(location.href).toBe('https://host.example/')
  })

  it('hands the tab to the app once the switch is on', () => {
    device()
    setOpenInAppEnabled(true)
    const setActiveId = vi.fn()
    openFromNotification('ses_a/b', setActiveId)
    expect(setActiveId).toHaveBeenCalledWith('ses_a/b')
    expect(location.href).toBe('claudepwa://open?ses=ses_a%2Fb')
    expect(location.href).toBe(appLink('ses_a/b'))
  })

  it('never hands off from a device that cannot have the app, even with the switch on', () => {
    device({ ua: MAC_UA, standalone: true, platform: 'MacIntel', touch: 0 })
    setOpenInAppEnabled(true)
    openFromNotification('ses_a', vi.fn())
    expect(location.href).toBe('https://host.example/')
  })
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
