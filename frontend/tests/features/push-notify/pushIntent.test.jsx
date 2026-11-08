// @vitest-environment jsdom
//
// 通知のオン・オフ (= 意思の印) と実際の購読の合わせ方の試験。 端末の購読の口と backend の口を作り物にし、
// 「オフにした後で端末が答えないまま画面が止まり、 前面に戻った時に見回りが購読し直す」 形を再現する。
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'

vi.mock('../../../src/_common/api.js', () => ({
  apiFetch: vi.fn(),
  apiUrl: (path) => path,
}))

import { apiFetch } from '../../../src/_common/api.js'
import { enablePush, disablePush, isPushEnabledLocally, setPushIntent } from '../../../src/features/push-notify/push.js'
import { usePushSubscription } from '../../../src/features/push-notify/usePushSubscription.js'
import { getSnapshot, _resetForTest } from '../../../src/state/push.js'

// 作り物の端末は鍵の中身を見ないので、 base64url として読める短い値で足りる
const KEY = 'AQID'

// 作り物の購読。 unsubscribe が返るかは試験が決める (= iOS で返らなかった形)
function fakeSubscription({ unsubscribeHangs = false } = {}) {
  const sub = {
    options: { applicationServerKey: null },
    toJSON: () => ({ endpoint: 'https://push.example/endpoint' }),
    unsubscribe: vi.fn(() => {
      device.current = null
      return unsubscribeHangs ? new Promise(() => {}) : Promise.resolve(true)
    }),
  }
  return sub
}

// 端末の購読の置き場。 getSubscription は今の購読を返し、 subscribe は試験が渡した promise で返す
const device = { current: null, nextSubscribe: null }

function installDevice() {
  const pushManager = {
    getSubscription: vi.fn(async () => device.current),
    subscribe: vi.fn(() => device.nextSubscribe ?? Promise.resolve(fakeSubscription())),
  }
  const registration = { pushManager }
  Object.defineProperty(navigator, 'serviceWorker', {
    configurable: true,
    value: { ready: Promise.resolve(registration), addEventListener: vi.fn(), removeEventListener: vi.fn() },
  })
  window.PushManager = function PushManager() {}
  window.Notification = { permission: 'granted', requestPermission: vi.fn(async () => 'granted') }
  globalThis.Notification = window.Notification
  return pushManager
}

function makeStorage() {
  const values = new Map()
  return {
    getItem: (key) => (values.has(key) ? values.get(key) : null),
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
    clear: () => values.clear(),
  }
}

function okResponse(body = {}) {
  return { ok: true, json: async () => body }
}

function called(path) {
  return apiFetch.mock.calls.filter(([p]) => p === path).length
}

async function settle() {
  for (let i = 0; i < 10; i++) await Promise.resolve()
}

let pushManager

beforeEach(() => {
  vi.stubGlobal('localStorage', makeStorage())
  _resetForTest()
  device.current = null
  device.nextSubscribe = null
  pushManager = installDevice()
  apiFetch.mockReset()
  apiFetch.mockImplementation(async (path) => (path === '/push/vapid-public-key' ? okResponse({ public_key: KEY }) : okResponse()))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('disablePush', () => {
  it('clears the intent before it waits for the device', async () => {
    setPushIntent(true)
    device.current = fakeSubscription({ unsubscribeHangs: true })
    const pending = disablePush()
    expect(isPushEnabledLocally()).toBe(false)
    await settle()
    expect(called('/push/unsubscribe')).toBe(1)
    expect(device.current).toBe(null)
    void pending
  })
})

describe('enablePush', () => {
  it('drops the subscription without handing it to the backend when the intent was turned off while subscribing', async () => {
    setPushIntent(true)
    let resolveSubscribe
    device.nextSubscribe = new Promise((resolve) => { resolveSubscribe = resolve })
    const running = enablePush()
    await settle()
    setPushIntent(false)
    const made = fakeSubscription()
    resolveSubscribe(made)
    expect(await running).toBe(false)
    expect(called('/push/subscribe')).toBe(0)
    expect(made.unsubscribe).toHaveBeenCalledTimes(1)
  })

  it('takes the subscription back from the backend when the intent was turned off while handing it over', async () => {
    setPushIntent(true)
    apiFetch.mockImplementation(async (path) => {
      if (path === '/push/vapid-public-key') return okResponse({ public_key: KEY })
      if (path === '/push/subscribe') setPushIntent(false)
      return okResponse()
    })
    expect(await enablePush()).toBe(false)
    expect(called('/push/subscribe')).toBe(1)
    expect(called('/push/unsubscribe')).toBe(1)
  })

  it('keeps the subscription while the intent stays on', async () => {
    setPushIntent(true)
    expect(await enablePush()).toBe(true)
    expect(called('/push/subscribe')).toBe(1)
    expect(called('/push/unsubscribe')).toBe(0)
  })
})

describe('usePushSubscription', () => {
  function mount() {
    const hub = renderHook(() => usePushSubscription({ mountEffects: true }))
    const toggle = renderHook(() => usePushSubscription())
    return { hub, toggle }
  }

  async function foreground() {
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'))
      await settle()
    })
  }

  it('turning off stays off when the device never answers the unsubscribe and the screen comes back later', async () => {
    setPushIntent(true)
    device.current = fakeSubscription({ unsubscribeHangs: true })
    const { hub, toggle } = mount()
    await act(async () => { await settle() })
    expect(getSnapshot().enabled).toBe(true)

    await act(async () => { await toggle.result.current.handleTogglePush(); await settle() })
    expect(getSnapshot().enabled).toBe(false)
    expect(getSnapshot().busy).toBe(false)

    await foreground()
    expect(called('/push/vapid-public-key')).toBe(0)
    expect(called('/push/subscribe')).toBe(0)
    expect(isPushEnabledLocally()).toBe(false)
    hub.unmount()
    toggle.unmount()
  })

  it('removes a subscription left behind after the intent was turned off', async () => {
    const left = fakeSubscription()
    device.current = left
    const { hub } = mount()
    await act(async () => { await settle() })
    expect(called('/push/unsubscribe')).toBe(1)
    expect(left.unsubscribe).toHaveBeenCalledTimes(1)
    expect(getSnapshot().enabled).toBe(false)
    hub.unmount()
  })

  it('still subscribes again when the intent is on and the subscription has lapsed', async () => {
    setPushIntent(true)
    const { hub } = mount()
    await act(async () => { await settle() })
    expect(called('/push/subscribe')).toBe(1)
    expect(getSnapshot().enabled).toBe(true)
    hub.unmount()
  })

  it('a failed turning on leaves the intent off', async () => {
    window.Notification.requestPermission = vi.fn(async () => 'denied')
    const alert = vi.spyOn(window, 'alert').mockImplementation(() => {})
    const { hub, toggle } = mount()
    await act(async () => { await settle() })
    await act(async () => { await toggle.result.current.handleTogglePush(); await settle() })
    expect(isPushEnabledLocally()).toBe(false)
    expect(alert).toHaveBeenCalledTimes(1)
    expect(pushManager.subscribe).not.toHaveBeenCalled()
    hub.unmount()
    toggle.unmount()
  })
})
