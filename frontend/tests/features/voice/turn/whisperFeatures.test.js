import { describe, it, expect } from 'vitest'
import { logMel, lastSeconds, melFilters, SAMPLES, MEL_BANDS, FRAMES } from '../../../../src/features/voice/turn/whisperFeatures.js'
import reference from './__fixtures__/whisper-features.json'

// 見本の音: 3 つの音の重ねに、 振幅のゆっくりした揺れ (= 見本の file を作った Python と同じ式)。
function sample() {
  const n = reference.samples
  const out = new Float32Array(n)
  for (let i = 0; i < n; i++) {
    const t = i / 16000
    out[i] = Math.fround((0.4 * Math.sin(2 * Math.PI * 220 * t) + 0.2 * Math.sin(2 * Math.PI * 1250 * t)
      + 0.1 * Math.sin(2 * Math.PI * 3100 * t)) * (0.6 + 0.4 * Math.sin(2 * Math.PI * 1.5 * t)))
  }
  return out
}

describe('logMel — the same features as Whisper\'s feature extractor', () => {
  const features = logMel(lastSeconds(sample()))

  it('has 80 bands of 800 frames', () => {
    expect(features).toHaveLength(MEL_BANDS * FRAMES)
    expect(MEL_BANDS * FRAMES).toBe(64000)
  })

  it('matches the values transformers gives for the same sound', () => {
    for (const [index, value] of Object.entries(reference.at)) {
      expect(Math.abs(features[Number(index)] - value)).toBeLessThan(1e-4)
    }
    const mean = features.reduce((a, b) => a + b, 0) / features.length
    expect(Math.abs(mean - reference.mean)).toBeLessThan(1e-5)
    expect(Math.abs(Math.max(...features) - reference.max)).toBeLessThan(1e-4)
    expect(Math.abs(Math.min(...features) - reference.min)).toBeLessThan(1e-4)
  })

  it('takes only exactly eight seconds of sound', () => {
    expect(() => logMel(new Float32Array(100))).toThrow(/128000/)
  })
})

describe('lastSeconds — the end of the sound, eight seconds long', () => {
  it('pads a short sound with silence at the start', () => {
    const out = lastSeconds(new Float32Array([0.5, -0.5]))
    expect(out).toHaveLength(SAMPLES)
    expect(Array.from(out.slice(-2))).toEqual([0.5, -0.5])
    expect(out[0]).toBe(0)
  })

  it('keeps the end of a long sound', () => {
    const long = new Float32Array(SAMPLES + 3)
    long[SAMPLES + 2] = 1
    const out = lastSeconds(long)
    expect(out).toHaveLength(SAMPLES)
    expect(out[SAMPLES - 1]).toBe(1)
  })
})

describe('melFilters — slaney mel bands from 0 to 8000 Hz', () => {
  it('gives each band a triangle that is never negative', () => {
    const filters = melFilters()
    expect(filters).toHaveLength(201 * 80)
    expect(Math.min(...filters)).toBeGreaterThanOrEqual(0)
  })
})
