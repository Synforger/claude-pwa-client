// PWA 通知から ?ses=xxx URL で該当 session に切替。
// useAppEffects.js から物理移送 (= W2 Phase C、 session 切替経路の責務)。
import { useEffect } from 'react'

import { setOverlay } from '../../state/ui.js'
import { startCall } from '../voice/voice.js'
import { listenAppLinks } from './appLinks.js'


// --- PWA 通知から ?ses=xxx URL で該当 session に切替 ---
// ?preview=<path> は、 外から file の口をタブで開いた時に backend が回す先。 その file を client の中の
// プレビュー (= 上の × で会話へ戻る) で開く。 ?ticket=<id> は、 票の通知から開いた時の、 票の画面。
// どれも一度読んでから history.replaceState で URL から除去する。
export function useDeepLink(setActiveId) {
  useEffect(() => {
    try {
      const sp = new URLSearchParams(window.location.search)
      const sid = sp.get('ses')
      const preview = sp.get('preview')
      const ticket = sp.get('ticket')
      if (!sid && !preview && !ticket) return
      const url = new URL(window.location.href)
      url.searchParams.delete('ses')
      url.searchParams.delete('preview')
      url.searchParams.delete('ticket')
      window.history.replaceState({}, '', url.toString())
      if (sid) setActiveId(sid)
      if (preview) setOverlay('previewPath', preview)
      if (ticket) setOverlay('ticket', ticket)
    } catch { /* ignore */ }
  }, [setActiveId])

  // app の中: app を開いた URL (= claudepwa://open?ses=xxx) のタブに切替。 Siri の「通話」 (= &call=1) なら、
  // そのタブで声とマイクの会話も始める。 票の通知の URL (= claudepwa://open?ticket=xxx) なら、 票の画面を開く。
  useEffect(() => listenAppLinks((sid, { call } = {}) => {
    setActiveId(sid)
    if (call) startCall(sid)
  }, (ticket) => setOverlay('ticket', ticket)), [setActiveId])
}
