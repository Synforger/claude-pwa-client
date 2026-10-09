import { describe, it, expect } from 'vitest'
import { INPUT_MAX_LINES, collapsedCap, fitHeight, expandedRect } from './inputSizing.js'

describe('collapsedCap', () => {
  it('is the height of the line limit plus the padding and the border', () => {
    expect(collapsedCap({ lineHeight: 20, padY: 16, borderY: 2 })).toBe(20 * INPUT_MAX_LINES + 18)
    expect(collapsedCap({ lineHeight: 20, padY: 16, borderY: 2 }, 3)).toBe(78)
  })
})

describe('fitHeight', () => {
  const cap = 150
  it('leaves the height alone while the text fits in the natural height', () => {
    expect(fitHeight({ content: 60, natural: 72, cap })).toEqual({ height: null, overflowing: false })
  })
  it('grows with the text once it is taller than the natural height', () => {
    expect(fitHeight({ content: 110, natural: 72, cap })).toEqual({ height: 110, overflowing: false })
  })
  it('is exactly at the limit without overflowing', () => {
    expect(fitHeight({ content: 150, natural: 72, cap })).toEqual({ height: 150, overflowing: false })
  })
  it('stops at the limit and reports the overflow', () => {
    expect(fitHeight({ content: 400, natural: 72, cap })).toEqual({ height: 150, overflowing: true })
  })
})

describe('expandedRect', () => {
  const slot = { left: 0, width: 390, bottom: 844, height: 92 }
  it('fills the chat area when nothing covers the screen', () => {
    const r = expandedRect({ areaTop: 96, slot, viewport: { top: 0, height: 844 } })
    expect(r).toEqual({ top: 96, left: 0, width: 390, height: 748 })
  })
  it('ends at the top of the on-screen keyboard', () => {
    // キーボードが 336px を覆い、 見えている範囲が 508px に縮んだ時
    const r = expandedRect({ areaTop: 96, slot, viewport: { top: 0, height: 508 } })
    expect(r).toEqual({ top: 96, left: 0, width: 390, height: 412 })
  })
  it('follows the visible range when the browser has scrolled the page under the keyboard', () => {
    // iOS は入力欄を見せるために頁ごと上へ送る (= 見えている範囲の上端が 0 でなくなる)
    const r = expandedRect({ areaTop: 96, slot, viewport: { top: 336, height: 508 } })
    expect(r).toEqual({ top: 336, left: 0, width: 390, height: 508 })
  })
  it('keeps the column of the chat area on a wide screen', () => {
    const wide = { left: 280, width: 1000, bottom: 800, height: 92 }
    const r = expandedRect({ areaTop: 96, slot: wide, viewport: { top: 0, height: 800 } })
    expect(r).toEqual({ top: 96, left: 280, width: 1000, height: 704 })
  })
  it('is never smaller than the collapsed input', () => {
    const r = expandedRect({ areaTop: 96, slot, viewport: { top: 0, height: 120 } })
    expect(r.height).toBe(92)
    expect(r.top + r.height).toBe(120)
  })
})
