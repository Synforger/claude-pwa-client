// @vitest-environment jsdom
//
// Which screens keep the tab list on the left: the query, the answer, and the follow of a window that changes size.
import { describe, it, expect, afterEach } from 'vitest'
import { DOCKED_SCREEN_QUERY, isDockedScreen, subscribeDockedScreen } from '../../../src/features/session-drawer/dockedScreen.js'
import { installFakeScreen, removeFakeScreen } from './fakeDockedScreen.js'

afterEach(removeFakeScreen)

describe('the screen that keeps the tab list on the left', () => {
  it('asks for a wide window with a mouse, and for nothing else', () => {
    expect(DOCKED_SCREEN_QUERY).toBe('(min-width: 1024px) and (hover: hover) and (pointer: fine)')
    const screen = installFakeScreen(true)
    isDockedScreen()
    expect(screen.asked).toEqual([DOCKED_SCREEN_QUERY])
  })

  it('answers with what the query matches', () => {
    const screen = installFakeScreen(true)
    expect(isDockedScreen()).toBe(true)
    screen.set(false)
    expect(isDockedScreen()).toBe(false)
  })

  it('is not a docked screen where the browser has no matchMedia (the tests, an old webview)', () => {
    expect(window.matchMedia).toBeUndefined()
    expect(isDockedScreen()).toBe(false)
    expect(() => subscribeDockedScreen(() => {})()).not.toThrow()
  })

  it('tells a listener when the window changes size, and stops after the returned function is called', () => {
    const screen = installFakeScreen(false)
    let calls = 0
    const stop = subscribeDockedScreen(() => { calls += 1 })
    screen.set(true)
    screen.set(false)
    expect(calls).toBe(2)
    stop()
    expect(screen.listenerCount()).toBe(0)
    screen.set(true)
    expect(calls).toBe(2)
  })
})
