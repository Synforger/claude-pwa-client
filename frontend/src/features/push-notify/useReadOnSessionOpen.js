// session を開いた時に既読化 (= backend 側の通知履歴を消す)。 useAppEffects.js から
// 物理移送 (= W2 Phase C、 push 通知系の責務をここに寄せる)。
import { useEffect } from 'react'
import { apiFetch } from '../../utils/api.js'


// --- session を開いた時に既読化 (= backend 側の通知履歴を消す) ---
// アプリバッジ数字は AppShell で useSessionBadges.unreadCount → setBadge 経路で
// 同期するので、 ここでは backend の read-all を投げるだけ (= push 通知センター用)。
//
// activeSid 高速切替 (= 100ms 以下で 4 タブ往復するケース) で POST が N 連発するのを
// 防ぐため 150ms debounce (= F-20)。 last-wins で「結果的に最後に居座った sid」 だけ
// 1 回 POST する。 unmount 時は pending を破棄 (= 切替直後にアンマウントしたら投げない)。
const READ_DEBOUNCE_MS = 150
export function useReadOnSessionOpen(activeSid) {
  useEffect(() => {
    if (!activeSid) return
    const timer = setTimeout(() => {
      apiFetch(`/notifications/read-all`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: activeSid }),
      }).catch(() => { /* ignore */ })
    }, READ_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [activeSid])
}
