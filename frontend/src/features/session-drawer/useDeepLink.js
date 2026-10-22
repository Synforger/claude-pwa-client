// PWA 通知から ?ses=xxx URL で該当 session に切替。
// useAppEffects.js から物理移送 (= W2 Phase C、 session 切替経路の責務)。
import { useEffect } from 'react'

import { setOverlay } from '../../state/ui.js'
import { startCall } from '../voice/voice.js'
import { listenAppLinks } from './appLinks.js'


// --- PWA 通知から ?ses=xxx URL で該当 session に切替 ---
// ?preview=<path> は、 外から file の口をタブで開いた時に backend が回す先。 その file を client の中の
// プレビュー (= 上の × で会話へ戻る) で開く。 どちらも一度読んでから history.replaceState で URL から除去する。
export function useDeepLink(setActiveId) {
  useEffect(() => {
    try {
      const sp = new URLSearchParams(window.location.search)
      const sid = sp.get('ses')
      const preview = sp.get('preview')
      if (!sid && !preview) return
      const url = new URL(window.location.href)
      url.searchParams.delete('ses')
      url.searchParams.delete('preview')
      window.history.replaceState({}, '', url.toString())
      if (sid) setActiveId(sid)
      if (preview) setOverlay('previewPath', preview)
    } catch { /* ignore */ }
  }, [setActiveId])

  // app の中: app を開いた URL (= claudepwa://open?ses=xxx) のタブに切替。 Siri の「通話」 (= &call=1) なら、
  // そのタブで声とマイクの会話も始める。
  useEffect(() => listenAppLinks((sid, { call } = {}) => {
    setActiveId(sid)
    if (call) startCall(sid)
  }), [setActiveId])
}
