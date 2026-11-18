// The arithmetic behind the pictures an attached image is drawn as: how a long side is scaled to fit, and which
// square of an image its thumbnail shows.
import { describe, it, expect } from 'vitest'
import { fitScale, thumbnailPlan } from '../../../src/features/attachments/imageGeometry.js'

describe('fitScale', () => {
  it('shrinks the long side to the limit', () => {
    expect(fitScale(4000, 3000, 2000)).toBe(0.5)
    expect(fitScale(3000, 4000, 2000)).toBe(0.5)
  })

  it('leaves an image that already fits', () => {
    expect(fitScale(1500, 1000, 2000)).toBe(1)
    expect(fitScale(2000, 2000, 2000)).toBe(1)
  })
})

describe('thumbnailPlan', () => {
  it('cuts the centred square of a landscape image and draws it at the thumbnail side', () => {
    expect(thumbnailPlan(1400, 1000, 540)).toEqual({ sourceX: 200, sourceY: 0, sourceSide: 1000, outputSide: 540 })
  })

  it('cuts the centred square of a portrait image', () => {
    expect(thumbnailPlan(1000, 2000, 540)).toEqual({ sourceX: 0, sourceY: 500, sourceSide: 1000, outputSide: 540 })
  })

  it('does not enlarge an image whose square is smaller than the thumbnail side', () => {
    expect(thumbnailPlan(400, 300, 540)).toEqual({ sourceX: 50, sourceY: 0, sourceSide: 300, outputSide: 300 })
  })

  it('gives a square image larger than the side a thumbnail drawn at the side', () => {
    expect(thumbnailPlan(1080, 1080, 540)).toEqual({ sourceX: 0, sourceY: 0, sourceSide: 1080, outputSide: 540 })
  })

  it('makes no thumbnail for a square image no larger than the side: it would not be smaller', () => {
    expect(thumbnailPlan(540, 540, 540)).toBeNull()
    expect(thumbnailPlan(100, 100, 540)).toBeNull()
  })

  it('makes no thumbnail for an image with no area', () => {
    expect(thumbnailPlan(0, 500, 540)).toBeNull()
  })

  it('rounds a centre that falls between pixels down', () => {
    expect(thumbnailPlan(1001, 1000, 540)).toEqual({ sourceX: 0, sourceY: 0, sourceSide: 1000, outputSide: 540 })
  })
})
