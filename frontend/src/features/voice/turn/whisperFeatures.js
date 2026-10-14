// Whisper と同じ log-mel の特徴 (= Smart Turn の model が受け取る形)。
//
// 写した原典: transformers の WhisperFeatureExtractor (= chunk_length 8、 do_normalize あり)。 Smart Turn の推論の
// 原典 (= pipecat-ai/smart-turn の inference.py) がこの設定で特徴を作っている。
//   1. 音 (= 16kHz、 8 秒ちょうど) を、 平均 0・分散 1 に揃える
//   2. 両端を 200 点ずつ鏡写しで伸ばし、 400 点の窓 (= 周期 hann) を 160 点ずつずらして、 各窓の強さの分布を取る
//   3. 80 本の mel の帯 (= slaney 型、 0〜8000Hz) にまとめて log10 を取る (= 最後の 1 窓は捨てて 800 窓)
//   4. 最大値から 8 を超えて小さい所を持ち上げ、 (x + 4) / 4 にする
// 返すのは [80 帯][800 窓] を 1 列に並べた Float32Array (= model の入力 `input_features` の [1, 80, 800])。
//
// Adapted from transformers (https://github.com/huggingface/transformers), Apache-2.0. 詳細 = THIRD_PARTY_NOTICES.md

export const SAMPLE_RATE = 16000
export const SECONDS = 8
export const SAMPLES = SAMPLE_RATE * SECONDS
const N_FFT = 400
const HOP = 160
export const MEL_BANDS = 80
export const FRAMES = SAMPLES / HOP
const BINS = N_FFT / 2 + 1

// --- mel の帯 (= transformers の audio_utils.mel_filter_bank、 norm と mel_scale は slaney) ---

const MIN_LOG_HERTZ = 1000
const MIN_LOG_MEL = 15
// 行き (= Hz → mel) と帰り (= mel → Hz) で、 対数の区間の係数は互いに逆数 (= 原典どおり)
const MEL_PER_LOG = 27 / Math.log(6.4)
const LOG_PER_MEL = Math.log(6.4) / 27
const hertzToMel = (f) => (f >= MIN_LOG_HERTZ ? MIN_LOG_MEL + Math.log(f / MIN_LOG_HERTZ) * MEL_PER_LOG : (3 * f) / 200)
const melToHertz = (m) => (m >= MIN_LOG_MEL ? MIN_LOG_HERTZ * Math.exp(LOG_PER_MEL * (m - MIN_LOG_MEL)) : (200 * m) / 3)

// [BINS][MEL_BANDS] (= 原典の mel_filters と同じ並び)
export function melFilters() {
  const melMin = hertzToMel(0)
  const melMax = hertzToMel(SAMPLE_RATE / 2)
  const edges = Array.from({ length: MEL_BANDS + 2 }, (_, i) => melToHertz(melMin + ((melMax - melMin) * i) / (MEL_BANDS + 1)))
  const fft = Array.from({ length: BINS }, (_, k) => ((SAMPLE_RATE / 2) * k) / (BINS - 1))
  const out = new Float64Array(BINS * MEL_BANDS)
  for (let k = 0; k < BINS; k++) {
    for (let m = 0; m < MEL_BANDS; m++) {
      const down = (fft[k] - edges[m]) / (edges[m + 1] - edges[m])
      const up = (edges[m + 2] - fft[k]) / (edges[m + 2] - edges[m + 1])
      const weight = Math.max(0, Math.min(down, up))
      out[k * MEL_BANDS + m] = weight * (2 / (edges[m + 2] - edges[m]))
    }
  }
  return out
}

// --- 窓と、 400 点の離散フーリエ変換の表 (= 実数の入力なので、 0〜200 番の周波数だけ) ---

let tables = null
function getTables() {
  if (tables) return tables
  const window = new Float64Array(N_FFT)
  for (let n = 0; n < N_FFT; n++) window[n] = 0.5 - 0.5 * Math.cos((2 * Math.PI * n) / N_FFT)
  const cos = new Float64Array(BINS * N_FFT)
  const sin = new Float64Array(BINS * N_FFT)
  for (let k = 0; k < BINS; k++) {
    for (let n = 0; n < N_FFT; n++) {
      const a = (2 * Math.PI * ((k * n) % N_FFT)) / N_FFT
      cos[k * N_FFT + n] = Math.cos(a)
      sin[k * N_FFT + n] = Math.sin(a)
    }
  }
  // 帯ごとに、 重みが 0 でない周波数の範囲だけを持つ (= 掛け算を減らす)
  const filters = melFilters()
  const bands = []
  for (let m = 0; m < MEL_BANDS; m++) {
    let from = -1
    let to = -1
    for (let k = 0; k < BINS; k++) {
      if (filters[k * MEL_BANDS + m] > 0) { if (from < 0) from = k; to = k }
    }
    // 重みが 1 つも無い帯 (= 周波数の刻みより細い低い帯) は、 強さ 0 として log を取る (= 原典と同じ値になる)
    const weights = new Float64Array(from < 0 ? 0 : to - from + 1)
    for (let k = from; from >= 0 && k <= to; k++) weights[k - from] = filters[k * MEL_BANDS + m]
    bands.push({ from: Math.max(from, 0), weights })
  }
  tables = { window, cos, sin, bands }
  return tables
}

// 8 秒ちょうど (= SAMPLES 点) の音を、 log-mel の特徴にする。
export function logMel(audio) {
  if (!(audio instanceof Float32Array) || audio.length !== SAMPLES) {
    throw new Error(`logMel needs ${SAMPLES} samples at ${SAMPLE_RATE}Hz`)
  }
  const { window, cos, sin, bands } = getTables()

  // 1. 平均 0・分散 1 (= 原典は numpy の var、 つまり n で割る分散に 1e-7 を足す)
  let mean = 0
  for (let i = 0; i < SAMPLES; i++) mean += audio[i]
  mean /= SAMPLES
  let variance = 0
  for (let i = 0; i < SAMPLES; i++) { const d = audio[i] - mean; variance += d * d }
  variance /= SAMPLES
  const scale = 1 / Math.sqrt(variance + 1e-7)

  // 2. 鏡写しで両端を伸ばす (= numpy の pad、 mode="reflect": 端の点そのものは繰り返さない)
  const half = N_FFT / 2
  const padded = new Float64Array(SAMPLES + N_FFT)
  for (let i = 0; i < SAMPLES; i++) padded[i + half] = (audio[i] - mean) * scale
  for (let i = 1; i <= half; i++) {
    padded[half - i] = padded[half + i]
    padded[half + SAMPLES - 1 + i] = padded[half + SAMPLES - 1 - i]
  }

  // 3. 窓ごとの強さ → mel の帯 → log10 (= 最後の 1 窓は原典どおり捨てる)
  const out = new Float32Array(MEL_BANDS * FRAMES)
  const frame = new Float64Array(N_FFT)
  const power = new Float64Array(BINS)
  let max = -Infinity
  for (let t = 0; t < FRAMES; t++) {
    const start = t * HOP
    for (let n = 0; n < N_FFT; n++) frame[n] = padded[start + n] * window[n]
    for (let k = 0; k < BINS; k++) {
      let re = 0
      let im = 0
      const row = k * N_FFT
      for (let n = 0; n < N_FFT; n++) { re += frame[n] * cos[row + n]; im -= frame[n] * sin[row + n] }
      // 原典は途中の複素数を 32 bit で持つ (= complex64)。 同じ丸めを通す
      const r = Math.fround(re)
      const i = Math.fround(im)
      power[k] = r * r + i * i
    }
    for (let m = 0; m < MEL_BANDS; m++) {
      const { from, weights } = bands[m]
      let sum = 0
      for (let j = 0; j < weights.length; j++) sum += weights[j] * power[from + j]
      const value = Math.log10(Math.max(sum, 1e-10))
      out[m * FRAMES + t] = value
      if (value > max) max = value
    }
  }

  // 4. 持ち上げと尺度
  const floor = max - 8
  for (let i = 0; i < out.length; i++) out[i] = (Math.max(out[i], floor) + 4) / 4
  return out
}

// 音の最後の 8 秒 (= 短ければ頭に 0 を足して 8 秒にする。 原典の truncate_audio_to_last_n_seconds)。
export function lastSeconds(audio) {
  if (audio.length === SAMPLES) return audio
  if (audio.length > SAMPLES) return audio.slice(audio.length - SAMPLES)
  const out = new Float32Array(SAMPLES)
  out.set(audio, SAMPLES - audio.length)
  return out
}
