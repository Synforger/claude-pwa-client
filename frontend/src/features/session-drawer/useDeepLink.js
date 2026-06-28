// PWA 通知から ?ses=xxx URL で該当 session に切替。
// useAppEffects.js から物理移送 (= W2 Phase C、 session 切替経路の責務)。
import { useEffect } from 'react'


// --- PWA 通知から ?ses=xxx URL で該当 session に切替 ---
// 一度読んでから history.replaceState で URL から除去する。
export function useDeepLink(setActiveId) {
  useEffect(() => {
    try {
      const sp = new URLSearchParams(window.location.search)
      const sid = sp.get('ses')
      if (sid) {
        setActiveId(sid)
        const url = new URL(window.location.href)
        url.searchParams.delete('ses')
        window.history.replaceState({}, '', url.toString())
      }
    } catch { /* ignore */ }
  }, [setActiveId])
}
