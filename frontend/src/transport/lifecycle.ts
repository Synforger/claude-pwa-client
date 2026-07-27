// Browser page lifecycle listener (= visibility / pagehide / pageshow / freeze)。
// ADR-013: beforeunload は意図的に listen しない (= BFCache 阻害)。
// pageshow.persisted で BFCache 復帰検知、 SSE/WS rebuild が必須。

import { unifiedTransport } from './select.ts'

const FG_EVENT = 'cpc:fg'
const BG_EVENT = 'cpc:bg'

// hidden から接続を落とすまでの猶予 (= 2026-07-15 R3)。 cmd-tab の一瞬の裏回りで
// 接続を作り直す churn を避けつつ、 裏に置かれたタブは完全ゼロ消費に落とす。
// 裏の間の通知は Web Push が担うので機能欠損なし、 復帰は visible bump の差分 replay。
const HIDDEN_STOP_GRACE_MS = 5_000
let hiddenStopTimer: ReturnType<typeof setTimeout> | null = null

let installed = false

export function installListeners(): void {
  if (installed) return
  installed = true
  if (typeof document === 'undefined' || typeof window === 'undefined') return
  document.addEventListener('visibilitychange', onVisibility)
  window.addEventListener('pagehide', onPagehide)
  window.addEventListener('pageshow', onPageshow)
  window.addEventListener('freeze', onFreeze)
  // beforeunload は意図的に listen しない (= BFCache 阻害源、 ADR-013)
}

export function uninstallListeners(): void {
  if (!installed) return
  installed = false
  if (typeof document === 'undefined' || typeof window === 'undefined') return
  document.removeEventListener('visibilitychange', onVisibility)
  window.removeEventListener('pagehide', onPagehide)
  window.removeEventListener('pageshow', onPageshow)
  window.removeEventListener('freeze', onFreeze)
}

function onVisibility(): void {
  if (document.visibilityState === 'visible') {
    if (hiddenStopTimer) { clearTimeout(hiddenStopTimer); hiddenStopTimer = null }
    // 統合 transport = 1 接続 bump で全 channel 蘇生 + 最新 snapshot 再取得。
    // iOS は bg で SSE を onerror なしに殺す (= silent-dead) ので、 復帰時 bump が唯一の
    // 確実な蘇生 + 初期 snapshot 再取得経路。
    unifiedTransport.bumpReconnect()
    window.dispatchEvent(new Event(FG_EVENT))
  } else {
    unifiedTransport.flushOffsets()
    // 「見てる」 登録を即時解除 (= 裏に置いたタブが push 通知を抑制し続けない)。
    unifiedTransport.suspendView()
    // 猶予後も hidden のままなら接続ごと停止 (= 裏タブ完全ゼロ消費、 R3)。
    // iOS は OS が先に殺すことが多いが、 Mac の裏タブはこれが唯一の停止経路。
    if (hiddenStopTimer) clearTimeout(hiddenStopTimer)
    hiddenStopTimer = setTimeout(() => {
      hiddenStopTimer = null
      if (document.visibilityState !== 'visible') unifiedTransport.stop()
    }, HIDDEN_STOP_GRACE_MS)
    window.dispatchEvent(new Event(BG_EVENT))
  }
}

function onPagehide(_e: PageTransitionEvent): void {
  unifiedTransport.flushOffsets()
  unifiedTransport.suspendView()
}

function onPageshow(e: PageTransitionEvent): void {
  if (e.persisted) {
    // BFCache 復帰 = transport rebuild 必須
    unifiedTransport.bumpReconnect()
    window.dispatchEvent(new Event(FG_EVENT))
  }
}

function onFreeze(): void {
  unifiedTransport.flushOffsets()
}
