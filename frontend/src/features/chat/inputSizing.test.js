import { describe, it, expect } from 'vitest'
import { INPUT_FOLDED_LINES, INPUT_OPEN_LINES, lineCap, fitHeight } from './inputSizing.js'

describe('lineCap', () => {
  it('is the height of the line limit plus the padding and the border', () => {
    expect(lineCap({ lineHeight: 20, padY: 16, borderY: 2 }, 3)).toBe(78)
    expect(lineCap({ lineHeight: 20, padY: 16, borderY: 2 }, 6)).toBe(138)
  })
})

describe('line limits', () => {
  it('folds to three lines and opens to six', () => {
    expect(INPUT_FOLDED_LINES).toBe(3)
    expect(INPUT_OPEN_LINES).toBe(6)
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
