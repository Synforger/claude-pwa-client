import { useState, useEffect, useMemo, useCallback, useSyncExternalStore } from 'react'
import '../App.css'
// W2 Phase E2 (= 2026-06-29): 全 7 overlay (= previewPath / treeOpen / favs / desktopOpen +
// SessionDrawer / SubagentsModal / TasksModal) の lazy + Suspense + render は OverlayHost に
// 完全集約。 AppShell は本 component 1 行配置だけで overlay 群の責務を完遂する (= 中央非依存)。
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

import StorageWarning from './StorageWarning.jsx'
import ConfirmDialog from '../shared/ConfirmDialog.jsx'
import ChatPanel from './ChatPanel.jsx'
import TerminalPane from './TerminalPane.jsx'
import {
  subscribe as subscribeUi,
  getSnapshot as getUiSnapshot,
  setOverlay,
  setViewMode,
  hydrate as hydrateUi,
} from '../state/ui.js'
import { useStatus } from '../features/status-bar/useStatus.js'
import { lsGet, lsSet } from '../utils/storage.js'
import { useSessions } from '../features/session-drawer/useSessions.js'
import { useStorageQuota } from '../features/status-bar/useStorageQuota.js'
import { useReadOnSessionOpen } from '../features/push-notify/useReadOnSessionOpen.js'
import { useNotificationClear } from '../features/push-notify/useNotificationClear.js'
import { useMoonlightAvailable } from '../features/screenshare/useMoonlightAvailable.js'
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
  // useSessions は singleton store を購読する hook なので、 ChatPanel と双方で呼ばれても state は
  // 共有される (= 二重 instance 化リスク無し)。
  const {
    sessions,
    activeId,
    setActiveId,
    removeSession,
  } = useSessions()

  const activeSession = useMemo(
    () => sessions.find(s => s.id === activeId) || null,
    [sessions, activeId],
  )
  // 全箇所共通の active セッション ID。 activeSession?.id を毎度書かない統一形。
  const activeSid = activeSession?.id || null

  // UI 局所 state (= overlays / viewModes / scroll / keyboard) を state/ui.js から 1 経路で pull。
  const ui = useSyncExternalStore(subscribeUi, getUiSnapshot)
  // タブごとの表示モード ('chat' | 'terminal')。 旧 useViewMode 派生値を ui.viewModes から再構築。
  const activeViewMode = useMemo(
    () => (activeSid ? (ui.viewModes[activeSid] || 'chat') : 'chat'),
    [activeSid, ui.viewModes],
  )
  const setActiveViewMode = useCallback((mode) => {
    if (!activeSid) return
    setViewMode(activeSid, mode)
  }, [activeSid])
  // viewModes を localStorage に書き戻す (= 旧 useViewMode の `useEffect(() => lsSet(KEY, viewModes))`
  // と同等)。 hydrate は module load 時に済ませているので、 ここは write 専任。
  useEffect(() => { lsSet(VIEW_MODES_LS_KEY, ui.viewModes) }, [ui.viewModes])
  // topbar の 📑 ボタン (= plan 承認待ち) は status.pending_plan で出すかを判定し、 click で
  // ui.overlays.planOpen を立てる。 PlanApprovalBubble 本体の render + auto-close は ChatPanel が
  // 担う (= W2 Phase F-1)。
  const status = useStatus(activeSession)

  const storageInfo = useStorageQuota()

  const [storageWarnDismissed, setStorageWarnDismissed] = useState(false)
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
  const moonlightAvailable = useMoonlightAvailable()

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

  const handleDeleteSession = async () => {
    const sid = ui.overlays.confirmDelete
    if (!sid) return
    setOverlay('confirmDelete', null)
    await removeSession(sid)
    // F-1 注: 旧 AppShell では setMessages で sid を dict から落として gcImages を即時呼出して
    // いたが、 messages / setMessages は ChatPanel が所有するようになったため、 ここでは追加 cleanup
    // を行わない。 useChatStorage.runMsgSave が sessions 更新を契機に v2 localStorage key を自動
    // remove するので永続化側は同等。 orphan IDB 画像は ChatPanel 内の起動時 1 回 GC + 次回再起動時
    // の GC で回収される (= 即時性は失うが整合性は保たれる、 review 確認事項参照)。
  }

  // Web Push 購読状態 (= 環境制約・トグル・連打防止) は専用 hook に集約。
  usePushSubscription()

  // W2 Phase F-2 (= 2026-06-29): Terminal LRU mount 経路は features/terminal/TerminalMount.jsx に
  // 集約、 wrapper は layout/TerminalPane.jsx (= always-mount + 内部 display:none gate)。 AppShell は
  // TerminalPane を 1 行配置するだけで terminal 領域の責務を完遂する (= 旧 LRU mount state +
  // F-11 LRU effect + session 削除 cleanup effect + render block 全削除済)。

  return (
    <div className="app">
      <StorageWarning
        info={storageInfo}
        dismissed={storageWarnDismissed}
        onDismiss={() => setStorageWarnDismissed(true)}
      />

      {/* ヘッダ: ハンバーガー + セッション名 + 画面共有 */}
      <header className="topbar">
        <button className="hamburger" onClick={() => setOverlay('drawer', true)} aria-label="会話一覧" data-testid="drawer-toggle">
          ☰
        </button>
        <span className="topbar-title">{activeSession?.title || '会話なし'}</span>
        {/* terminal モード時の chat 復帰ボタン: ⋯メニュー経由が hit test 等で詰まっても
            ここから確実に戻れるよう topbar に独立表示。 chat モード時は出さない。 */}
        {activeViewMode === 'terminal' && activeSid && (
          <button
            className="topbar-icon-btn"
            onClick={() => setActiveViewMode('chat')}
            aria-label="チャット表示に戻す"
            title="チャット表示に戻す"
          >
            💬
          </button>
        )}
        {/* topbar 右側のアイコン群。 並びは左→右で ⭐ お気に入り → 📋 タスク →
            🤖 サブエージェント → (📑 plan 承認、 条件付き) → 🖥 モニター。 */}
        {activeViewMode === 'chat' && activeSid && (
          <button
            className="topbar-icon-btn"
            onClick={() => setOverlay('favs', true)}
            aria-label="お気に入り"
            title="お気に入りに飛ぶ"
            data-testid="favorites-open-button"
          >
            ⭐
          </button>
        )}
        {activeViewMode === 'chat' && activeSid && (
          <button
            className="topbar-icon-btn"
            onClick={() => setOverlay('tasks', true)}
            aria-label="タスク"
            title="タスク一覧"
            data-testid="tasks-open-button"
          >
            📋
          </button>
        )}
        {activeViewMode === 'chat' && activeSid && (
          <button
            className="topbar-icon-btn"
            onClick={() => { setOverlay('subagentsFocus', null); setOverlay('subagents', true) }}
            aria-label="サブエージェント"
            title="サブエージェント一覧"
            data-testid="subagents-open-button"
          >
            🤖
          </button>
        )}
        {/* ExitPlanMode 承認待ち: 🤖 の隣に常駐する 📑 ボタン。 pending_plan がある時のみ表示、
            脈動ドットで承認待ちを示し、 タップで PlanApprovalBubble (= ChatPanel 内) を開く
            (= ui.overlays.planOpen 経由)。 */}
        {activeViewMode === 'chat' && activeSid && status?.pending_plan && (
          <button
            className="topbar-icon-btn topbar-plan-btn"
            onClick={() => setOverlay('planOpen', true)}
            aria-label="plan 承認待ち"
            title="plan 承認"
            data-testid="plan-approval-open-button"
          >
            📑<span className="topbar-plan-dot" />
          </button>
        )}
        {moonlightAvailable && (
          <button
            className={`screen-toggle ${ui.overlays.desktopOpen ? 'active' : ''}`}
            onClick={() => setOverlay('desktopOpen', !ui.overlays.desktopOpen)}
            aria-label="画面共有"
            title={ui.overlays.desktopOpen ? '画面共有を閉じる' : '画面共有を開く (Sunshine 経由、 ペア済前提)'}
            data-testid="screenshare-toggle"
          >
            🖥
          </button>
        )}
      </header>

      {/* W2 Phase F-2 (= 2026-06-29): terminal 領域の always-mount owner。 LRU + visible gate +
          Terminal 本体描画は features/terminal/TerminalMount.jsx + layout/TerminalPane.jsx が担う。
          AppShell からは sid props を渡すだけで、 内部で state/ui.js + state/sessions.js を自前
          subscribe して LRU を回す (= 旧 AppShell の LRU mount state + 2 useEffect 退役)。 */}
      <TerminalPane sid={activeSid} />

      {/* W2 Phase F-1: chat 経路の自己完結 owner。 hidden 制御は ChatPanel 内部で activeViewMode を
          subscribe して display 切替する (= always mount = chat 状態の lifecycle を保つ)。 */}
      <ChatPanel sid={activeSid} />

      <ConfirmDialog
        open={!!ui.overlays.confirmDelete}
        text={
          <>
            この会話を削除しますか？
            <br />
            <span className="dim">会話履歴も削除されます。 元に戻せません。</span>
          </>
        }
        onCancel={() => setOverlay('confirmDelete', null)}
        onConfirm={handleDeleteSession}
      />

      {/* W2 Phase E2: overlayRegistry に Component spec を持つ entry (= 7 件: previewPath /
          treeOpen / favs / desktopOpen + drawer / subagents / tasks) を 1 経路で lazy + Suspense
          + LazyBoundary render する中央 host。 features/<x>/index.js が起動時 self-register、
          AppShell は本 component 1 行配置だけで該当 overlay 群の責務を完遂する (= 中央非依存)。 */}
      <OverlayHost />
    </div>
  )
}
