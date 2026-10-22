import { describe, expect, it } from 'vitest'
import { scrollToKeep, spread, wheelFactor } from '../../src/_common/textZoom.js'

describe('textZoom gestures', () => {
  it('turns the wheel into a factor the way d3-zoom does', () => {
    expect(wheelFactor(0, 0)).toBe(1)
    expect(wheelFactor(-50, 0)).toBeCloseTo(2, 10)        // pixels: 2 ** (50 × 0.002 × 10)
    expect(wheelFactor(50, 0)).toBeCloseTo(0.5, 10)
    expect(wheelFactor(-2, 1)).toBeCloseTo(2, 10)         // lines: 2 ** (2 × 0.05 × 10)
    expect(wheelFactor(-0.1, 2)).toBeCloseTo(2, 10)       // pages: 2 ** (0.1 × 1 × 10)
  })

  it('measures the distance between two fingers', () => {
    expect(spread([{ clientX: 0, clientY: 0 }, { clientX: 30, clientY: 40 }])).toBe(50)
  })

  it('scrolls so that what was under the fingers stays there', () => {
    // The text was 1000 tall starting 200 above the screen; the fingers were at 300, a quarter
    // of the way in. Twice as tall after: that quarter is now 500 further down.
    expect(scrollToKeep({ top: -200, height: 1000 }, { top: -200, height: 2000 }, 300)).toBe(500)
    expect(scrollToKeep({ top: 0, height: 0 }, { top: 0, height: 100 }, 50)).toBe(-50)
  })
})
