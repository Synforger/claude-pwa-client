// 最下端への張り付き判定の検査。 外れるのは上へのスクロールだけで、 中身が伸びて距離が開いても
// 外れないこと (= 開いた時 / ↓ ボタンで途中に止まる不具合の根)。
import { describe, it, expect } from 'vitest'
import { nextStuck, AT_BOTTOM_THRESHOLD_PX } from './stickToBottom.js'

const at = (over) => ({ stuck: true, prevTop: 1000, top: 1000, scrollHeight: 1600, clientHeight: 600, ...over })

describe('features/chat — stick to bottom', () => {
  it('stays stuck when content grows under it (distance opens, scrollTop unchanged)', () => {
    // 送った直後に中身が 400px 伸びた: 距離 400 だが上へは動いていない
    expect(nextStuck(at({ scrollHeight: 2000 }))).toBe(true)
  })

  it('stays stuck while being scrolled down toward the new bottom', () => {
    expect(nextStuck(at({ prevTop: 1000, top: 1200, scrollHeight: 2400 }))).toBe(true)
  })

  it('escapes when the user scrolls up', () => {
    expect(nextStuck(at({ prevTop: 1000, top: 900 }))).toBe(false)
  })

  it('ignores sub-pixel jitter', () => {
    expect(nextStuck(at({ prevTop: 1000, top: 999.5, scrollHeight: 2000 }))).toBe(true)
  })

  it('re-sticks when the user comes back near the bottom', () => {
    expect(nextStuck(at({ stuck: false, prevTop: 900, top: 1000 - AT_BOTTOM_THRESHOLD_PX + 5 }))).toBe(true)
  })

  it('stays unstuck while reading older messages and scrolling down a little', () => {
    expect(nextStuck(at({ stuck: false, prevTop: 200, top: 300 }))).toBe(false)
  })

  it('stays stuck when the content shrinks and the browser clamps scrollTop down to the new bottom', () => {
    // details を閉じて高さが減り、 scrollTop が新しい最下端に引き戻された (= 上への移動に見える)
    expect(nextStuck(at({ prevTop: 1000, top: 800, scrollHeight: 1400 }))).toBe(true)
  })
})
