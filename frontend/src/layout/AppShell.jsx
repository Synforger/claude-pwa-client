import { useEffect, useSyncExternalStore } from 'react'
import '../App.css'
// W2 Phase F-4 (= 2026-06-29): StorageWarning の JSX は features/status-bar/StorageWarningHost.jsx
// に物理移送済。 CSS (= layout/StorageWarning.css) のみ AppShell が intra-layer side-effect import
// で引き続き load する (= features → layout boundaries 制約回避、 .storage-warn 系 class 定義は
// 重複させない)。 旧 layout/StorageWarning.jsx 本体は dead file (= 別 phase で退役予定)。
import './StorageWarning.css'
// W2 Phase E2 (= 2026-06-29): 全 7 overlay (= previewPath / treeOpen / favs / desktopOpen +
// SessionDrawer / SubagentsModal / TasksModal) + W2 Phase F-4 (= confirmDelete) の lazy +
// Suspense + render は OverlayHost に完全集約。 AppShell は本 component 1 行配置だけで overlay
// 群の責務を完遂する (= 中央非依存)。
import OverlayHost from './OverlayHost.jsx'

// features/* self-register (= ADR-010、 設計書 § 9-6 step 5)。 各 entry が
// streamRegistry / messageRegistry / overlayRegistry / pushRegistry / featureRegistry に
// register call で配線、 App.jsx は本 side-effect import で 1 経路で全 feature を載せる。
import '../features/chat/index.js'
import '../features/session-drawer/index.js'
import '../features/status-bar/index.js'
import '../features/file-preview/index.js'
import '../features/file-tree/index.js'
import '../features/ask-user-question/index.js'
import '../features/plan-approval/index.js'
import '../features/screenshare/index.js'
import '../features/subagents/index.js'
import '../features/tasks/index.js'
import '../features/push-notify/index.js'
import '../features/attachments/index.js'
import '../features/ios-native/index.js'
import '../features/terminal/index.js'
import '../features/fork/index.js'
import '../features/topbar/index.js'
import '../features/dialogs/index.js'

import ChatPanel from './ChatPanel.jsx'
import TerminalPane from './TerminalPane.jsx'
import Topbar from '../features/topbar/Topbar.jsx'
import StorageWarningHost from '../features/status-bar/StorageWarningHost.jsx'
import {
  subscribe as subscribeUi,
  getSnapshot as getUiSnapshot,
  setOverlay,
  hydrate as hydrateUi,
} from '../state/ui.js'
import { lsGet, lsSet } from '../utils/storage.js'
import { useSessions } from '../features/session-drawer/useSessions.js'
import { useReadOnSessionOpen } from '../features/push-notify/useReadOnSessionOpen.js'
import { useNotificationClear } from '../features/push-notify/useNotificationClear.js'
import { useDeepLink } from '../features/session-drawer/useDeepLink.js'
import { usePushSubscription } from '../features/push-notify/usePushSubscription.js'

// viewModes (= タブごとの chat/terminal 表示モード) の localStorage 永続化キー (= 旧 useViewMode 継承)。
// state/ui.js は persistence 非対応、 ここで hydrate + write を担う。 module load 時に 1 回 hydrate
// しておくことで AppShell の first render で `ui.viewModes` が即座に正しい値になる
// (= 旧 useViewMode の `useState(() => lsGet(LS_KEY) || {})` 同等の挙動を再現)。
const VIEW_MODES_LS_KEY = 'cpc_view_modes'
try {
  const persisted = lsGet(VIEW_MODES_LS_KEY)
  if (persisted && typeof persisted === 'object') hydrateUi({ viewModes: persisted })
} catch { /* hydrate 失敗は viewModes={} で起動して継続 (= 旧 hook の try/lsGet と同方針) */ }

export default function AppShell() {
  // セッション (= UI 上のタブ = 1 議題) 管理。 W2 Phase F-1 (= 2026-06-29): chat 経路 hook 群は
  // ChatPanel.jsx に物理移送、 AppShell は topbar / Terminal / session-level dialog の責務のみ。
  // W2 Phase F-3 (= 2026-06-29): topbar 経路は features/topbar/Topbar.jsx に物理移送、 AppShell は
  // <Topbar /> 1 行配置で完結。 activeSid 取得は deep-link 経路 (= ?ses= URL 反映 + SW への
  // active-session post + activeSession 切替時の useReadOnSessionOpen) で必要なので、 ここで継続購読。
  const {
    sessions,
    activeId,
    setActiveId,
  } = useSessions()

  // 全箇所共通の active セッション ID。
  const activeSid = sessions.find(s => s.id === activeId)?.id || null

  // UI 局所 state (= overlays / viewModes / scroll / keyboard) を state/ui.js から 1 経路で pull。
  const ui = useSyncExternalStore(subscribeUi, getUiSnapshot)
  // viewModes を localStorage に書き戻す (= 旧 useViewMode の `useEffect(() => lsSet(KEY, viewModes))`
  // と同等)。 hydrate は module load 時に済ませているので、 ここは write 専任。
  useEffect(() => { lsSet(VIEW_MODES_LS_KEY, ui.viewModes) }, [ui.viewModes])

  // overlay 11 系 (= drawer / menu / favs / tasks / subagents (+ Focus) / previewPath / treeOpen /
  // confirmEnd / confirmStop / confirmDelete) は state/ui.js.overlays.* に統合済 (= W2 Phase B、
  // 旧 useOverlays 廃止)。 読み = `ui.overlays.X`、 書き = `setOverlay('X', value)`。
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

  // W2 Phase F-2 (= 2026-06-29): Terminal LRU mount 経路は features/terminal/TerminalMount.jsx に
  // 集約、 wrapper は layout/TerminalPane.jsx (= always-mount + 内部 display:none gate)。 AppShell は
  // TerminalPane を 1 行配置するだけで terminal 領域の責務を完遂する (= 旧 LRU mount state +
  // F-11 LRU effect + session 削除 cleanup effect + render block 全削除済)。

  return (
    <div className="app">
      {/* W2 Phase F-4 (= 2026-06-29): StorageWarning の useStorageQuota 呼出 + dismissed state +
          render は features/status-bar/StorageWarningHost.jsx に物理移送。 AppShell からは本
          component 1 行配置で完結 (= 旧 storageInfo / storageWarnDismissed state 退役)。 */}
      <StorageWarningHost />

      {/* W2 Phase F-3 (= 2026-06-29): topbar 経路は features/topbar/Topbar.jsx に物理移送。
          AppShell からは <Topbar /> 1 行配置で完結 (= status / moonlight / viewMode / activeSession
          の各購読は Topbar 内部で自前解決)。 */}
      <Topbar />

      {/* W2 Phase F-2 (= 2026-06-29): terminal 領域の always-mount owner。 LRU + visible gate +
          Terminal 本体描画は features/terminal/TerminalMount.jsx + layout/TerminalPane.jsx が担う。
          AppShell からは sid props を渡すだけで、 内部で state/ui.js + state/sessions.js を自前
          subscribe して LRU を回す (= 旧 AppShell の LRU mount state + 2 useEffect 退役)。 */}
      <TerminalPane sid={activeSid} />

      {/* W2 Phase F-1: chat 経路の自己完結 owner。 hidden 制御は ChatPanel 内部で activeViewMode を
          subscribe して display 切替する (= always mount = chat 状態の lifecycle を保つ)。 */}
      <ChatPanel sid={activeSid} />

      {/* W2 Phase E2 + Phase F-4: overlayRegistry に Component spec を持つ entry (= 8 件:
          previewPath / treeOpen / favs / desktopOpen + drawer / subagents / tasks + confirmDelete)
          を 1 経路で lazy + Suspense + LazyBoundary render する中央 host。 features/<x>/index.js が
          起動時 self-register、 AppShell は本 component 1 行配置だけで該当 overlay 群の責務を完遂
          する (= 中央非依存)。 */}
      <OverlayHost />
    </div>
  )
}
