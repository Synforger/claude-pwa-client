// PWA 起動時 / visibility 復帰時に通知センター + バッジ + backend カウンタを掃除。
// useAppEffects.js から物理移送 (= W2 Phase C、 push 通知系の責務をここに寄せる)。
import { useEffect } from 'react'
import { clearAllNotifications } from './badge.js'


// --- PWA 起動時 / visibility 復帰時に通知センター + バッジ + backend カウンタを掃除 ---
// iOS PWA は通知センターに通知が残ってる間アプリバッジを「未読通知数」 で上書きする
// 挙動があるので、 通知本体を能動的に close しないとバッジが消えない。 backend の
// `unread_count` global も累積され続ける (= push のたびに +1) ため、 ここで sync で 0 に
// 上書きする。 backend が新たに push を飛ばすと再度カウントが立つ。
export function useNotificationClear() {
  useEffect(() => {
    // mount 時 1 回
    clearAllNotifications()
    // visibility 復帰時にも
    const onVis = () => {
      if (!document.hidden) clearAllNotifications()
    }
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [])
}
