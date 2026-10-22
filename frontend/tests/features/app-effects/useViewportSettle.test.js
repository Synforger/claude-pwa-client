// @vitest-environment jsdom
//
// キーボードが閉じた後に文書の送りが残ったら 0 へ戻し、 その時の値を記録へ 1 行送る。 入力中と、 送りが無い時は
// 何もしない (= 記録の行は「戻した時」 だけに出るので、 ずれが残ったのに行が無ければ原因は別の所)。
import { describe, it, expect, vi, afterEach } from 'vitest'
import { settleViewport } from '../../../src/features/app-effects/useViewportSettle.js'

function scrolledBy(y) {
  Object.defineProperty(window, 'scrollY', { configurable: true, value: y })
}

afterEach(() => {
  scrolledBy(0)
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('settleViewport', () => {
  it('brings a document left scrolled back to the top, and reports the values it found', () => {
    scrolledBy(287)
    const scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
    const send = vi.fn()
    expect(settleViewport('viewport', send)).toBe(true)
    expect(scrollTo).toHaveBeenCalledWith(0, 0)
    expect(send).toHaveBeenCalledTimes(1)
    expect(send.mock.calls[0][0]).toMatchObject({ stage: 'viewport:settle', trigger: 'viewport', scrollY: 287 })
    expect(send.mock.calls[0][0]).toHaveProperty('innerHeight')
  })

  it('leaves the document alone while an input is focused (= the keyboard is up)', () => {
    scrolledBy(287)
    document.body.innerHTML = '<textarea></textarea>'
    document.querySelector('textarea').focus()
    const scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
    const send = vi.fn()
    expect(settleViewport('viewport', send)).toBe(false)
    expect(scrollTo).not.toHaveBeenCalled()
    expect(send).not.toHaveBeenCalled()
  })

  it('does nothing and reports nothing when the document is not scrolled', () => {
    const scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
    const send = vi.fn()
    expect(settleViewport('visible', send)).toBe(false)
    expect(scrollTo).not.toHaveBeenCalled()
    expect(send).not.toHaveBeenCalled()
  })

  it('settles once a focused button, not an input, holds the focus', () => {
    scrolledBy(120)
    document.body.innerHTML = '<button>Send</button>'
    document.querySelector('button').focus()
    vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
    const send = vi.fn()
    expect(settleViewport('viewport', send)).toBe(true)
  })
})
