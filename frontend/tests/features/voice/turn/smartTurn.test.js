import { describe, it, expect } from 'vitest'
import { createSmartTurn, COMPLETE_ABOVE, judgedPart } from '../../../../src/features/voice/turn/smartTurn.js'

// 作り物の onnxruntime: 渡された入力を覚えて、 決まった確率を返す。
function fakeOrt(probability) {
  const seen = []
  class Tensor { constructor(type, data, dims) { Object.assign(this, { type, data, dims }) } }
  const InferenceSession = {
    create: async (model, options) => {
      seen.push({ model, options })
      return {
        inputNames: ['input_features'],
        outputNames: ['logits'],
        run: async (feeds) => { seen.push({ feeds }); return { logits: { data: new Float32Array([probability]) } } },
      }
    },
  }
  return { ort: { Tensor, InferenceSession }, seen }
}

describe('createSmartTurn — whether the speaker has finished', () => {
  it('gives the model the last eight seconds as Whisper features, shaped [1, 80, 800]', async () => {
    const { ort, seen } = fakeOrt(0.9)
    const turn = await createSmartTurn({ ort, model: new ArrayBuffer(4) })
    expect(seen[0].model).toBeInstanceOf(Uint8Array)
    expect(seen[0].options.executionProviders).toEqual(['wasm'])
    expect(await turn.probability(new Float32Array(16000))).toBeCloseTo(0.9)
    const input = seen[1].feeds.input_features
    expect(input.type).toBe('float32')
    expect(input.dims).toEqual([1, 80, 800])
    expect(input.data).toHaveLength(64000)
  })

  it('calls it finished only above one half, as the original does', async () => {
    expect(COMPLETE_ABOVE).toBe(0.5)
    expect(await (await createSmartTurn(fakeOrt(0.51))).complete(new Float32Array(10))).toBe(true)
    expect(await (await createSmartTurn(fakeOrt(0.5))).complete(new Float32Array(10))).toBe(false)
  })
})

describe('judgedPart — Smart Turn sees as much silence after the voice as Pipecat gives it', () => {
  it('cuts the longer wait off the end, keeping 6 frames (0.2 s) of it', () => {
    const audio = new Float32Array(100 * 512)
    // 0.7 s = 21 frames of 32 ms come after the voice; Smart Turn keeps 6 of them
    expect(judgedPart(audio, 700).length).toBe((100 - 15) * 512)
  })

  it('leaves the voice as it is when the wait is already 0.2 s', () => {
    const audio = new Float32Array(100 * 512)
    expect(judgedPart(audio, 200)).toBe(audio)
  })

  it('never cuts into a voice shorter than the wait', () => {
    const audio = new Float32Array(10 * 512)
    expect(judgedPart(audio, 700)).toBe(audio)
  })
})
