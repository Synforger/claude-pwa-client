// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  UPDATE_CHECK_INTERVAL_MS,
  runningBuildId,
  checkForUpdate,
  fetchServedBuildId,
  installUpdateChecks,
  _resetForTest,
} from '../../src/_common/appUpdate.js'

// service worker の入れ物の代わり: 登録の update() を数え、 controllerchange を手で起こせる
function fakeNavigator({ controlled }) {
  const listeners = {}
  const registration = { update: vi.fn(() => Promise.resolve()) }
  return {
    registration,
    serviceWorker: {
      controller: controlled ? {} : null,
      getRegistration: vi.fn(() => Promise.resolve(registration)),
      addEventListener: (type, fn) => { (listeners[type] ||= []).push(fn) },
    },
    fire: (type) => { for (const fn of listeners[type] || []) fn() },
  }
}

function fakeWindow() {
  const target = new EventTarget()
  const stored = new Map()
  return {
    location: { reload: vi.fn() },
    sessionStorage: {
      getItem: (key) => (stored.has(key) ? stored.get(key) : null),
      setItem: (key, value) => { stored.set(key, String(value)) },
    },
    addEventListener: target.addEventListener.bind(target),
    dispatchEvent: target.dispatchEvent.bind(target),
    setInterval: (fn, ms) => setInterval(fn, ms),
  }
}

beforeEach(() => { vi.useFakeTimers(); _resetForTest(); document.head.innerHTML = '' })
afterEach(() => { vi.useRealTimers() })

describe('runningBuildId', () => {
  it('reads the build off the entry script the page loaded', () => {
    document.head.innerHTML = '<script type="module" crossorigin src="/assets/index-mXKnAty4.js"></script>'
    expect(runningBuildId()).toBe('mXKnAty4')
  })

  it('is null when the page has no entry script (dev server, tests)', () => {
    document.head.innerHTML = '<script type="module" src="/src/main.jsx"></script>'
    expect(runningBuildId()).toBeNull()
  })
})

describe('checkForUpdate', () => {
  it('asks the registration to look for a new service worker', async () => {
    const nav = fakeNavigator({ controlled: true })
    await checkForUpdate(nav)
    expect(nav.registration.update).toHaveBeenCalledTimes(1)
  })

  it('does not throw when the check fails (offline)', async () => {
    const nav = fakeNavigator({ controlled: true })
    nav.registration.update.mockImplementation(() => Promise.reject(new Error('offline')))
    await expect(checkForUpdate(nav)).resolves.toBeUndefined()
  })

  it('does nothing where there is no service worker', async () => {
    await expect(checkForUpdate({})).resolves.toBeUndefined()
  })
})

describe('installUpdateChecks', () => {
  it('reloads once when a new service worker takes over a page that already had one', () => {
    const nav = fakeNavigator({ controlled: true })
    const win = fakeWindow()
    installUpdateChecks({ win, doc: document, nav })
    nav.fire('controllerchange')
    nav.fire('controllerchange')
    expect(win.location.reload).toHaveBeenCalledTimes(1)
  })

  it('does not reload for the first registration, and does for the update after it', () => {
    // 初めて開いた頁: service worker が付く (= 更新ではない) → その後に新しい版が来る
    const nav = fakeNavigator({ controlled: false })
    const win = fakeWindow()
    installUpdateChecks({ win, doc: document, nav })
    nav.fire('controllerchange')
    expect(win.location.reload).not.toHaveBeenCalled()
    nav.fire('controllerchange')
    expect(win.location.reload).toHaveBeenCalledTimes(1)
  })

  // 未送信の添付の見張りの代わり: 在る / 無いを手で切り替え、 変わった知らせを聞き手へ送る
  function fakeUnsent(initial) {
    let any = initial
    const listeners = new Set()
    return {
      hasAny: () => any,
      subscribe: (fn) => { listeners.add(fn); return () => listeners.delete(fn) },
      set: (value) => { any = value; for (const fn of [...listeners]) fn() },
      listeners,
    }
  }

  it('reloads at once when nothing unsent is on the screen', () => {
    const nav = fakeNavigator({ controlled: true })
    const win = fakeWindow()
    installUpdateChecks({ win, doc: document, nav, unsent: fakeUnsent(false) })
    nav.fire('controllerchange')
    expect(win.location.reload).toHaveBeenCalledTimes(1)
  })

  it('holds the reload while an attachment is picked but not sent, and reloads once it is gone', () => {
    const nav = fakeNavigator({ controlled: true })
    const win = fakeWindow()
    const unsent = fakeUnsent(true)
    installUpdateChecks({ win, doc: document, nav, unsent })
    nav.fire('controllerchange')
    expect(win.location.reload).not.toHaveBeenCalled()
    // 別の変化 (= もう 1 つ足した等) では移らない
    unsent.set(true)
    expect(win.location.reload).not.toHaveBeenCalled()
    // 送った / 外した
    unsent.set(false)
    expect(win.location.reload).toHaveBeenCalledTimes(1)
    // 以後の変化では読み込み直さず、 見張りも外れている
    unsent.set(true)
    unsent.set(false)
    expect(win.location.reload).toHaveBeenCalledTimes(1)
    expect(unsent.listeners.size).toBe(0)
  })

  it('a second new build during the hold does not add a second reload', () => {
    const nav = fakeNavigator({ controlled: true })
    const win = fakeWindow()
    const unsent = fakeUnsent(true)
    installUpdateChecks({ win, doc: document, nav, unsent })
    nav.fire('controllerchange')
    nav.fire('controllerchange')
    expect(unsent.listeners.size).toBe(1)
    unsent.set(false)
    expect(win.location.reload).toHaveBeenCalledTimes(1)
  })

  it('checks for a new build when the app comes back to the foreground', async () => {
    const nav = fakeNavigator({ controlled: true })
    const win = fakeWindow()
    installUpdateChecks({ win, doc: document, nav })
    expect(nav.registration.update).not.toHaveBeenCalled()
    win.dispatchEvent(new Event('cpc:fg'))
    await vi.advanceTimersByTimeAsync(0)
    expect(nav.registration.update).toHaveBeenCalledTimes(1)
  })

  it('checks at the interval while the app is visible, and not while it is hidden', async () => {
    const nav = fakeNavigator({ controlled: true })
    const win = fakeWindow()
    const doc = { visibilityState: 'visible', querySelector: (q) => document.querySelector(q) }
    installUpdateChecks({ win, doc, nav })
    await vi.advanceTimersByTimeAsync(UPDATE_CHECK_INTERVAL_MS)
    expect(nav.registration.update).toHaveBeenCalledTimes(1)
    doc.visibilityState = 'hidden'
    await vi.advanceTimersByTimeAsync(UPDATE_CHECK_INTERVAL_MS * 3)
    expect(nav.registration.update).toHaveBeenCalledTimes(1)
    doc.visibilityState = 'visible'
    await vi.advanceTimersByTimeAsync(UPDATE_CHECK_INTERVAL_MS)
    expect(nav.registration.update).toHaveBeenCalledTimes(2)
  })

  it('wires itself once', () => {
    const nav = fakeNavigator({ controlled: true })
    const win = fakeWindow()
    installUpdateChecks({ win, doc: document, nav })
    installUpdateChecks({ win, doc: document, nav })
    nav.fire('controllerchange')
    expect(win.location.reload).toHaveBeenCalledTimes(1)
    win.dispatchEvent(new Event('cpc:fg'))
    expect(nav.serviceWorker.getRegistration).toHaveBeenCalledTimes(1)
  })
})

// 入口の頁を配る backend の代わり: 配っている build を差し替えられ、 取りに来た回数を数える
function fakeHttp(build) {
  const http = {
    build,
    fail: false,
    apiFetch: vi.fn((path) => {
      if (http.fail) return Promise.reject(new Error('offline'))
      const html = `<!doctype html><html><head><script type="module" crossorigin src="/assets/index-${http.build}.js"></script></head></html>`
      return Promise.resolve({ ok: path === '/', text: () => Promise.resolve(html) })
    }),
  }
  return http
}

describe('fetchServedBuildId', () => {
  it('reads the build off the entry page the backend serves now', async () => {
    await expect(fetchServedBuildId(fakeHttp('NEWbuild1'))).resolves.toBe('NEWbuild1')
  })

  it('is null when the entry page cannot be fetched (offline)', async () => {
    const http = fakeHttp('NEWbuild1')
    http.fail = true
    await expect(fetchServedBuildId(http)).resolves.toBeNull()
  })
})

describe('installUpdateChecks without a service worker (the iPhone app)', () => {
  // service worker の口が無い入れ物で、 今の画面が OLDbuild1 を動かしている
  function setup({ served = 'NEWbuild1', unsent = null } = {}) {
    document.head.innerHTML = '<script type="module" crossorigin src="/assets/index-OLDbuild1.js"></script>'
    const win = fakeWindow()
    const http = fakeHttp(served)
    const send = vi.fn()
    installUpdateChecks({ win, doc: document, nav: {}, unsent, http, send })
    const foreground = async () => {
      win.dispatchEvent(new Event('cpc:fg'))
      await vi.advanceTimersByTimeAsync(0)
    }
    return { win, http, send, foreground }
  }

  it('reloads once when the backend serves another build, and records the move', async () => {
    const { win, send, foreground } = setup()
    await foreground()
    expect(win.location.reload).toHaveBeenCalledTimes(1)
    expect(send).toHaveBeenCalledWith({ stage: 'update:reload', from: 'OLDbuild1', to: 'NEWbuild1', serviceWorker: false })
    await foreground()
    expect(win.location.reload).toHaveBeenCalledTimes(1)
  })

  it('does not reload while the backend serves the build the screen runs', async () => {
    const { win, http, send, foreground } = setup({ served: 'OLDbuild1' })
    await foreground()
    expect(http.apiFetch).toHaveBeenCalledWith('/')
    expect(win.location.reload).not.toHaveBeenCalled()
    expect(send).not.toHaveBeenCalled()
  })

  it('does not reload when the entry page cannot be fetched', async () => {
    const { win, http, foreground } = setup()
    http.fail = true
    await foreground()
    expect(win.location.reload).not.toHaveBeenCalled()
  })

  it('holds the reload while an attachment is picked but not sent', async () => {
    let any = true
    const listeners = new Set()
    const unsent = {
      hasAny: () => any,
      subscribe: (fn) => { listeners.add(fn); return () => listeners.delete(fn) },
    }
    const { win, foreground } = setup({ unsent })
    await foreground()
    expect(win.location.reload).not.toHaveBeenCalled()
    any = false
    for (const fn of [...listeners]) fn()
    expect(win.location.reload).toHaveBeenCalledTimes(1)
  })

  it('does not reload again for a build it already reloaded to (the entry page stayed old somewhere)', async () => {
    document.head.innerHTML = '<script type="module" crossorigin src="/assets/index-OLDbuild1.js"></script>'
    const win = fakeWindow()
    win.sessionStorage.setItem('cpc_update_reloaded_to', 'NEWbuild1')
    installUpdateChecks({ win, doc: document, nav: {}, http: fakeHttp('NEWbuild1'), send: vi.fn() })
    win.dispatchEvent(new Event('cpc:fg'))
    await vi.advanceTimersByTimeAsync(0)
    expect(win.location.reload).not.toHaveBeenCalled()
  })

  it('remembers the build it reloaded to', async () => {
    const { win, foreground } = setup()
    await foreground()
    expect(win.sessionStorage.getItem('cpc_update_reloaded_to')).toBe('NEWbuild1')
  })

  it('does nothing on a page without an entry script (dev server)', async () => {
    document.head.innerHTML = '<script type="module" src="/src/main.jsx"></script>'
    const win = fakeWindow()
    const http = fakeHttp('NEWbuild1')
    installUpdateChecks({ win, doc: document, nav: {}, http, send: vi.fn() })
    win.dispatchEvent(new Event('cpc:fg'))
    await vi.advanceTimersByTimeAsync(UPDATE_CHECK_INTERVAL_MS)
    expect(http.apiFetch).not.toHaveBeenCalled()
  })

  it('checks at the interval while the app is visible, and not while it is hidden', async () => {
    document.head.innerHTML = '<script type="module" crossorigin src="/assets/index-OLDbuild1.js"></script>'
    const win = fakeWindow()
    const http = fakeHttp('OLDbuild1')
    const doc = { visibilityState: 'hidden', querySelector: (q) => document.querySelector(q) }
    installUpdateChecks({ win, doc, nav: {}, http, send: vi.fn() })
    await vi.advanceTimersByTimeAsync(UPDATE_CHECK_INTERVAL_MS * 2)
    expect(http.apiFetch).not.toHaveBeenCalled()
    doc.visibilityState = 'visible'
    await vi.advanceTimersByTimeAsync(UPDATE_CHECK_INTERVAL_MS)
    expect(http.apiFetch).toHaveBeenCalledTimes(1)
  })
})

describe('installUpdateChecks with a service worker that does not take the screen over', () => {
  // ホーム画面の PWA: service worker は在るが、 新しい版が有効になった知らせが画面に届かない
  function setup(served) {
    document.head.innerHTML = '<script type="module" crossorigin src="/assets/index-OLDbuild1.js"></script>'
    const nav = fakeNavigator({ controlled: true })
    const win = fakeWindow()
    const http = fakeHttp(served)
    const send = vi.fn()
    installUpdateChecks({ win, doc: document, nav, http, send })
    const foreground = async () => {
      win.dispatchEvent(new Event('cpc:fg'))
      await vi.advanceTimersByTimeAsync(0)
    }
    return { nav, win, send, foreground }
  }

  it('moves once the entry page names another build, and still asks the service worker to update', async () => {
    const { nav, win, send, foreground } = setup('NEWbuild1')
    await foreground()
    expect(nav.registration.update).toHaveBeenCalledTimes(1)
    expect(win.location.reload).toHaveBeenCalledTimes(1)
    expect(send).toHaveBeenCalledWith({ stage: 'update:reload', from: 'OLDbuild1', to: 'NEWbuild1', serviceWorker: true })
  })

  it('reloads once when both the entry page and the new service worker notice the build', async () => {
    const { nav, win, foreground } = setup('NEWbuild1')
    await foreground()
    nav.fire('controllerchange')
    expect(win.location.reload).toHaveBeenCalledTimes(1)
  })

  it('stays while the entry page names the build the screen runs', async () => {
    const { win, foreground } = setup('OLDbuild1')
    await foreground()
    expect(win.location.reload).not.toHaveBeenCalled()
  })
})
