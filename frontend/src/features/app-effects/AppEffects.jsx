// AppShell.jsx に残っていた app-wide effect 群を 1 経路に集約する不可視 component
// (= W2 Phase F-5、 2026-06-29)。 旧 AppShell.jsx の以下責務を物理移送、 ロジック改変ゼロ:
//   - viewModes localStorage write (= ui.viewModes 変化で lsSet)
//   - document.visibilityState=hidden で desktopOpen overlay を強制 close
//   - useReadOnSessionOpen(activeSid) (= active タブ切替で既読化)
//   - useDeepLink(setActiveId) (= ?ses= URL から session 切替)
//   - useNotificationClear() (= 通知クリア)
//   - URL ?ses= 直読み + setActiveId (= 起動直後の deep-link 経路、 useDeepLink と並走、
//     旧 AppShell から duplicate のまま移送 = 挙動再現性優先で原状維持)
//   - SW への active-session post (= visibility 連動 + activeSid 変化)
//   - usePushSubscription() (= Web Push 購読状態管理)
//
// hydrate (= module load 時の lsGet → state/ui.hydrate({viewModes})) も本 file の module-level で行う
// (= 旧 AppShell.jsx の module-level hydrate と同方針、 first render で ui.viewModes が即座に正しい値
// になる)。 mount 1 経路前提、 layout/Layout.jsx で <AppEffects /> を 1 行配置するだけで全副作用が
// 起動する (= Layout は配置 host、 副作用は本 sentinel)。
//
// return null = 不可視。 React tree への影響なし、 boundaries (= features → layout 禁止) も触らない。

import { useEffect } from 'react'
import { useSessions } from '../session-drawer/useSessions.js'
import { useReadOnSessionOpen } from '../push-notify/useReadOnSessionOpen.js'
import { useNotificationClear } from '../push-notify/useNotificationClear.js'
import { useDeepLink } from '../session-drawer/useDeepLink.js'
import { usePushSubscription } from '../push-notify/usePushSubscription.js'
import {
  subscribe as subscribeUi,
  getSnapshot as getUiSnapshot,
  setOverlay,
  hydrate as hydrateUi,
} from '../../state/ui.js'
import { lsGet, lsSet } from '../../utils/storage.js'
import { useSyncExternalStore } from 'react'

// viewModes (= タブごとの chat/terminal 表示モード) の localStorage 永続化キー (= 旧 useViewMode 継承)。
// state/ui.js は persistence 非対応、 ここで hydrate + write を担う。 module load 時に 1 回 hydrate
// しておくことで Layout.jsx の first render で `ui.viewModes` が即座に正しい値になる
// (= 旧 useViewMode の `useState(() => lsGet(LS_KEY) || {})` 同等の挙動を再現)。
const VIEW_MODES_LS_KEY = 'cpc_view_modes'
try {
  const persisted = lsGet(VIEW_MODES_LS_KEY)
  if (persisted && typeof persisted === 'object') hydrateUi({ viewModes: persisted })
} catch { /* hydrate 失敗は viewModes={} で起動して継続 (= 旧 hook の try/lsGet と同方針) */ }

export default function AppEffects() {
  const { sessions, activeId, setActiveId } = useSessions()
  const activeSid = sessions.find(s => s.id === activeId)?.id || null
  const ui = useSyncExternalStore(subscribeUi, getUiSnapshot)

  // viewModes を localStorage に書き戻す (= 旧 useViewMode の `useEffect(() => lsSet(KEY, viewModes))`
  // と同等)。 hydrate は module load 時に済ませているので、 ここは write 専任。
  useEffect(() => { lsSet(VIEW_MODES_LS_KEY, ui.viewModes) }, [ui.viewModes])

  // 画面共有 (= Sunshine ストリーム) は見てる間だけ生かす。 PWA がバックグラウンド / 画面ロック
  // に入ったら iframe を unmount して WebRTC を切る。 復帰時は自動再開せず、 ユーザが 🖥 を再タップ
  // して開き直す。
  useEffect(() => {
    const onHidden = () => { if (document.hidden) setOverlay('desktopOpen', false) }
    document.addEventListener('visibilitychange', onHidden)
    return () => document.removeEventListener('visibilitychange', onHidden)
  }, [])

  // backend / 通知 / deep link 系の effect は feature ごとの hook に分散 (= W2 Phase C 移送済)
  useReadOnSessionOpen(activeSid)
  useDeepLink(setActiveId)
  useNotificationClear()

  // 通知タップで PWA が完全終了状態から起動された場合、 SW の openWindow が
  // /?ses=<sid> 付きで起動するので、 ここで URL param を読んで activeId に反映する。
  // (= 旧 AppShell から原状維持で移送、 useDeepLink と並走するが挙動同一で無害)
  useEffect(() => {
    try {
      const sid = new URLSearchParams(window.location.search).get('ses')
      if (sid) {
        setActiveId(sid)
        const url = new URL(window.location.href)
        url.searchParams.delete('ses')
        window.history.replaceState({}, '', url.pathname + (url.search || '') + url.hash)
      }
    } catch (e) {

      console.warn('[deep-link] URL ?ses= parse failed:', e)
    }
  }, [setActiveId])

  // 今 active で見ている session を SW に伝える (= sw.js の LINE 流抑制で使う)。
  useEffect(() => {
    if (!('serviceWorker' in navigator)) return
    const post = () => {
      const ctrl = navigator.serviceWorker.controller
      if (!ctrl) return
      ctrl.postMessage({
        type: 'active-session',
        sid: document.visibilityState === 'visible' ? (activeSid || null) : null,
      })
    }
    post()
    document.addEventListener('visibilitychange', post)
    return () => document.removeEventListener('visibilitychange', post)
  }, [activeSid])

  // Web Push 購読状態 (= 環境制約・トグル・連打防止) は専用 hook に集約。
  usePushSubscription()

  return null
}
