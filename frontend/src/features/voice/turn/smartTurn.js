// Smart Turn (= pipecat-ai/smart-turn): 人の声の最後の 8 秒から、 言い終えたか (= まだ考え中か) を判定する。
//
// 写した原典: pipecat-ai/smart-turn の inference.py。 音の最後の 8 秒を Whisper と同じ特徴にして model に渡し、
// model が返す確率 (= 言い終えた確からしさ) が 0.5 を超えれば「言い終えた」。
//
// Adapted from smart-turn (https://github.com/pipecat-ai/smart-turn), BSD-2-Clause. 詳細 = THIRD_PARTY_NOTICES.md

import { logMel, lastSeconds, MEL_BANDS, FRAMES } from './whisperFeatures.js'

// 原典の inference.py の判定の境目
export const COMPLETE_ABOVE = 0.5

// Smart Turn に見せる声の後ろの無音 (= Pipecat の既定。 pipecat の base_smart_turn.py の stop_secs と、 それを
// 受ける VAD の stop_secs 0.2 秒)
export const JUDGE_TAIL_MS = 200
// 声の区間の検出の 1 枠 (= Silero VAD v5 は 16kHz の 512 点ずつ見る。 @ricky0123/vad-web の frameSamples)
const VAD_FRAME_SAMPLES = 512
const VAD_FRAME_MS = (VAD_FRAME_SAMPLES / 16000) * 1000

// 声の区間の検出は、 区間の後ろに「途切れた」 と言うまでの無音 (= pauseMs 分の枠) を付けて渡す。 Smart Turn は声の
// 後ろの無音が長いほど「言い終えた」 に寄るので、 判定に見せる無音は Pipecat と同じ JUDGE_TAIL_MS 分に切る。
export function judgedPart(audio, pauseMs) {
  const extra = (Math.floor(pauseMs / VAD_FRAME_MS) - Math.floor(JUDGE_TAIL_MS / VAD_FRAME_MS)) * VAD_FRAME_SAMPLES
  return extra > 0 && audio.length > extra ? audio.subarray(0, audio.length - extra) : audio
}

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
