import { useEffect } from 'react'
import { httpClient } from '../../transport/http.ts'
import { drainPerfSamples, readPerfContext } from './perfProbe.js'

// iPhone 実機の main thread 詰まり観測 (= 2026-07-10 発熱調査の観測点)。
//
// PerformanceObserver('longtask') は WebKit 非対応なので、 interval の実測 drift で代替する:
// TICK_MS ごとの実行が予定より STALL_MIN_MS 以上遅れた回数と合計遅延を、 REPORT_INTERVAL
// ごとに backend の /log/sw へ beacon する (= logs/backend.log で `perf:stall` を grep して
// stall rate を読める)。 計測自体の負荷は 2 Hz の減算 1 回で無視できる。
//
// 読み方: stalls が常時 2 桁 / 分なら main thread が恒常的に詰まっている (= 発熱と直結)。
// streaming markdown 間引き (= useThrottledStreamingText) の前後比較にもこの数値を使う。
const CLIENT_TAG = (() => {
  const ua = typeof navigator !== 'undefined' ? navigator.userAgent : ''
  const device = /iPhone/.test(ua) ? 'iphone' : /iPad/.test(ua) ? 'ipad' : /Mac/.test(ua) ? 'mac' : 'other'
  const standalone = typeof window !== 'undefined' && window.matchMedia?.('(display-mode: standalone)')?.matches
  const tab = Math.random().toString(36).slice(2, 6)
  return `${device}${standalone ? '-pwa' : '-tab'}-${tab}`
})()

const TICK_MS = 500
const STALL_MIN_MS = 200
const REPORT_INTERVAL_MS = 60_000

export function usePerfBeacon() {
  useEffect(() => {
    let last = Date.now()
    let stalls = 0
    let stallMs = 0
    let ticks = 0
    const tick = setInterval(() => {
      const now = Date.now()
      const drift = now - last - TICK_MS
      last = now
      ticks += 1
      if (drift >= STALL_MIN_MS) {
        stalls += 1
        stallMs += drift
      }
    }, TICK_MS)
    const report = setInterval(() => {
      // background 中は iOS が interval 自体を絞るので drift が計測にならない。 捨てて仕切り直し。
      const visible = typeof document === 'undefined' || document.visibilityState === 'visible'
      // 段階 2 (= 2026-07-13): 容疑者の実測 (= slow) と transcript 規模 (= ctx) を同乗。
      // 独立 request を増やさず 1 beacon に相乗りさせる (= 無線コスト据え置き)。
      const slow = drainPerfSamples()
      const ctx = readPerfContext()
      const payload = {
        stage: 'perf:stall',
        // 複数クライアント (= iPhone PWA + Mac タブ) の beacon が同じログに混ざり
        // 端末別の切り分けが不能だった (= 2026-07-13 判明)。 UA から粗い機種タグ +
        // tab 単位の乱数 id で層別できるようにする。
        client: CLIENT_TAG,
        stalls,
        stall_ms: Math.round(stallMs),
        ticks,
        window_ms: REPORT_INTERVAL_MS,
        ...(slow ? { slow } : {}),
        ...(ctx ? { ctx } : {}),
      }
      stalls = 0; stallMs = 0; ticks = 0
      last = Date.now()
      if (!visible || payload.ticks === 0) return
      httpClient.apiFetch('/log/sw', { method: 'POST', jsonBody: payload }).catch(() => {})
    }, REPORT_INTERVAL_MS)
    return () => {
      clearInterval(tick)
      clearInterval(report)
    }
  }, [])
}
