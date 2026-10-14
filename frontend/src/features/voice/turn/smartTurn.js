// Smart Turn (= pipecat-ai/smart-turn): 人の声の最後の 8 秒から、 言い終えたか (= まだ考え中か) を判定する。
//
// 写した原典: pipecat-ai/smart-turn の inference.py。 音の最後の 8 秒を Whisper と同じ特徴にして model に渡し、
// model が返す確率 (= 言い終えた確からしさ) が 0.5 を超えれば「言い終えた」。
//
// Adapted from smart-turn (https://github.com/pipecat-ai/smart-turn), BSD-2-Clause. 詳細 = THIRD_PARTY_NOTICES.md

import { logMel, lastSeconds, MEL_BANDS, FRAMES } from './whisperFeatures.js'

// 原典の inference.py の判定の境目
export const COMPLETE_ABOVE = 0.5

// ort = onnxruntime-web、 model = model の file の中身 (= ArrayBuffer か Uint8Array)。
export async function createSmartTurn({ ort, model }) {
  const session = await ort.InferenceSession.create(model instanceof Uint8Array ? model : new Uint8Array(model), {
    executionProviders: ['wasm'],
    graphOptimizationLevel: 'all',
  })
  const [inputName] = session.inputNames
  const [outputName] = session.outputNames
  return {
    // 16kHz の声 (= Float32Array) → 言い終えた確からしさ (= 0〜1)
    async probability(audio) {
      const features = new ort.Tensor('float32', logMel(lastSeconds(audio)), [1, MEL_BANDS, FRAMES])
      const out = await session.run({ [inputName]: features })
      return Number(out[outputName].data[0])
    },
    async complete(audio) {
      return (await this.probability(audio)) > COMPLETE_ABOVE
    },
  }
}
