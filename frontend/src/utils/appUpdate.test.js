// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  UPDATE_CHECK_INTERVAL_MS,
  runningBuildId,
  checkForUpdate,
  installUpdateChecks,
  _resetForTest,
} from './appUpdate.js'

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
  return {
    location: { reload: vi.fn() },
    addEventListener: target.addEventListener.bind(target),
    dispatchEvent: target.dispatchEvent.bind(target),
    setInterval: (fn, ms) => setInterval(fn, ms),
  }
}

beforeEach(() => { vi.useFakeTimers(); _resetForTest() })
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
    const doc = { visibilityState: 'visible' }
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
