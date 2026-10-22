import { describe, it, expect } from 'vitest'
import { encodeWav } from '../../../src/features/voice/wav.js'

describe('encodeWav — 16-bit mono PCM in a WAV file', () => {
  it('writes the header and the samples, clipped to the 16-bit range', async () => {
    const blob = encodeWav(new Float32Array([0, 1, -1, 2, 0.5]), 16000)
    expect(blob.type).toBe('audio/wav')
    const view = new DataView(await blob.arrayBuffer())
    const text = (at, n) => String.fromCharCode(...Array.from({ length: n }, (_, i) => view.getUint8(at + i)))
    expect(text(0, 4)).toBe('RIFF')
    expect(text(8, 8)).toBe('WAVEfmt ')
    expect(view.getUint16(22, true)).toBe(1)
    expect(view.getUint32(24, true)).toBe(16000)
    expect(view.getUint16(34, true)).toBe(16)
    expect(text(36, 4)).toBe('data')
    expect(view.getUint32(40, true)).toBe(10)
    expect([0, 1, 2, 3, 4].map((i) => view.getInt16(44 + i * 2, true))).toEqual([0, 32767, -32768, 32767, 16383])
  })
})
