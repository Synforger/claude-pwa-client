// 発熱調査 段階 2 の観測点 (= 2026-07-13)。 perf:stall beacon は「いつ main thread が
// 詰まったか」 しか見えないので、 容疑者 (= markdown 描画 / 履歴永続化) の実測時間と
// 実行時コンテキストを毎分の beacon に同乗させ、 「何が詰まらせたか」 を特定する。
//
// 設計:
// - recordPerfSample(name, ms, meta): 各容疑者が自分の所要時間を投げ込む。 リングは
//   MAX_SAMPLES で頭打ち (= 長い streaming でもメモリ一定)、 溢れた分は件数と合計 ms
//   だけ集計に残る (= 取りこぼしを黙って捨てない)。
// - drainPerfSamples(): beacon が毎分呼ぶ。 所要時間の大きい順に TOP_N 件 + 全体集計を
//   返してリングを空にする (= 閾値でなく top-N なので「何 ms から遅いか」 の恣意的な
//   足切り値を持たない)。
// - registerPerfContext(fn): 描画中 transcript の規模 (= メッセージ数 / 文字数) を返す
//   getter を登録する。 beacon が毎分 1 回だけ呼ぶので O(n) 集計でも負荷は無視できる。

const MAX_SAMPLES = 64
const TOP_N = 8

let samples = []
let overflowCount = 0
let overflowMs = 0
let contextProvider = null

export function recordPerfSample(name, ms, meta = {}) {
  if (samples.length >= MAX_SAMPLES) {
    overflowCount += 1
    overflowMs += ms
    return
  }
  samples.push({ name, ms: Math.round(ms * 10) / 10, ...meta })
}

export function drainPerfSamples() {
  const all = samples
  samples = []
  const totalMs = all.reduce((a, s) => a + s.ms, 0) + overflowMs
  const count = all.length + overflowCount
  overflowCount = 0
  overflowMs = 0
  if (count === 0) return null
  const top = [...all].sort((a, b) => b.ms - a.ms).slice(0, TOP_N)
  return { count, total_ms: Math.round(totalMs), top }
}

export function registerPerfContext(fn) {
  contextProvider = fn
  return () => {
    if (contextProvider === fn) contextProvider = null
  }
}

export function readPerfContext() {
  try {
    return contextProvider ? contextProvider() : null
  } catch {
    return null
  }
}

// test 用: モジュール状態を初期化する。
export function _resetPerfProbe() {
  samples = []
  overflowCount = 0
  overflowMs = 0
  contextProvider = null
}
