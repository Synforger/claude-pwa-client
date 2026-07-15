// Browser page lifecycle listener (= visibility / pagehide / pageshow / freeze)。
// ADR-013: beforeunload は意図的に listen しない (= BFCache 阻害)。
// pageshow.persisted で BFCache 復帰検知、 SSE/WS rebuild が必須。

import { sseTransport } from './sse.ts'
import { viewsTransport } from './ws-views.ts'
import { bumpAllSubscribedSse } from './_sse.ts'
import { unifiedEnabled, unifiedTransport } from './select.ts'

const FG_EVENT = 'cpc:fg'
const BG_EVENT = 'cpc:bg'

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
    if (unifiedEnabled) {
      // 統合 transport = 1 接続 bump で全 channel 蘇生 + 最新 snapshot 再取得
      // (= 旧構成の「4-5 本を各自張り直す」 無線バーストが 1 本に)
      unifiedTransport.bumpReconnect()
    } else {
      sseTransport.bumpReconnect()
      // _sse factory 系 (= sessions-status / sessions-overview / subagents) も張り直す。
      // iOS は bg で SSE を onerror なしに殺す (= silent-dead) ので、 復帰時 bump が唯一の
      // 確実な蘇生 + 初期 snapshot 再取得経路 (= 📋 tasks / model / ctx の凍結根治)。
      bumpAllSubscribedSse()
      viewsTransport.start()
    }
    window.dispatchEvent(new Event(FG_EVENT))
  } else {
    if (unifiedEnabled) {
      unifiedTransport.flushOffsets()
      // 「見てる」 登録を即時解除 (= 裏に置いたタブが push 通知を抑制し続けない)。
      // 旧 /views/ws の「hidden = WS close = 登録消滅」 と同じ意味論を明示送信で再現。
      unifiedTransport.suspendView()
    } else {
      sseTransport.flushOffsets()
      viewsTransport.stop()
    }
    window.dispatchEvent(new Event(BG_EVENT))
  }
}

function onPagehide(e: PageTransitionEvent): void {
  if (unifiedEnabled) {
    unifiedTransport.flushOffsets()
    unifiedTransport.suspendView()
  } else {
    sseTransport.flushOffsets()
    if (!e.persisted) viewsTransport.stop()
  }
}

function onPageshow(e: PageTransitionEvent): void {
  if (e.persisted) {
    // BFCache 復帰 = transport rebuild 必須
    if (unifiedEnabled) {
      unifiedTransport.bumpReconnect()
    } else {
      sseTransport.bumpReconnect()
      bumpAllSubscribedSse()
      viewsTransport.start()
    }
    window.dispatchEvent(new Event(FG_EVENT))
  }
}

function onFreeze(): void {
  if (unifiedEnabled) unifiedTransport.flushOffsets()
  else sseTransport.flushOffsets()
}
