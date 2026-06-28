// Browser page lifecycle listener (= visibility / pagehide / pageshow / freeze)。
// ADR-013: beforeunload は意図的に listen しない (= BFCache 阻害)。
// pageshow.persisted で BFCache 復帰検知、 SSE/WS rebuild が必須。

import { sseTransport } from './sse.ts'
import { viewsTransport } from './ws-views.ts'

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
    sseTransport.bumpReconnect()
    viewsTransport.start()
    window.dispatchEvent(new Event(FG_EVENT))
  } else {
    sseTransport.flushOffsets()
    viewsTransport.stop()
    window.dispatchEvent(new Event(BG_EVENT))
  }
}

function onPagehide(e: PageTransitionEvent): void {
  sseTransport.flushOffsets()
  if (!e.persisted) viewsTransport.stop()
}

function onPageshow(e: PageTransitionEvent): void {
  if (e.persisted) {
    // BFCache 復帰 = transport rebuild 必須
    sseTransport.bumpReconnect()
    viewsTransport.start()
    window.dispatchEvent(new Event(FG_EVENT))
  }
}

function onFreeze(): void {
  sseTransport.flushOffsets()
}
