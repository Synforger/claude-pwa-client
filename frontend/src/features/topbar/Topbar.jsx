// topbar 経路の自己完結 owner (= W2 Phase F-3、 2026-06-29)。 旧 AppShell.jsx の `<header className="topbar">`
// block を物理移送、 ロジック改変ゼロ。 各 button の onClick は内部で setOverlay 直呼出 + 必要な store
// (= sessions / ui / status) は自前 subscribe で解決する (= ADR-010 props 自己解決契約)。
//
// AppShell からは <Topbar /> 1 行配置のみ。 常時 mount component (= overlay でない) なので
// registerFeature 経由で配線、 Component lazy spec は不要 (= main bundle 同梱で OK、
// features/__contracts__/no-lazy-component-static-import.test.js の Component spec 件数は不変)。

import { useSyncExternalStore, useMemo, useCallback } from 'react'
import {
  subscribe as subscribeUi,
  getSnapshot as getUiSnapshot,
  setOverlay,
  setViewMode,
} from '../../state/ui.js'
import {
  subscribe as subscribeSessions,
  getSnapshot as getSessionsSnapshot,
} from '../../state/sessions.js'
import { useStatus } from '../status-bar/useStatus.js'
import { useMoonlightAvailable } from '../screenshare/useMoonlightAvailable.js'

export default function Topbar() {
  const ui = useSyncExternalStore(subscribeUi, getUiSnapshot)
  const sessionsState = useSyncExternalStore(subscribeSessions, getSessionsSnapshot)

  const activeSession = useMemo(
    () => sessionsState.sessions.find(s => s.id === sessionsState.activeId) || null,
    [sessionsState.sessions, sessionsState.activeId],
  )
  const activeSid = activeSession?.id || null
  const activeViewMode = useMemo(
    () => (activeSid ? (ui.viewModes[activeSid] || 'chat') : 'chat'),
    [activeSid, ui.viewModes],
  )
  const setActiveViewMode = useCallback((mode) => {
    if (!activeSid) return
    setViewMode(activeSid, mode)
  }, [activeSid])

  // topbar の 📑 ボタン (= plan 承認待ち) は status.pending_plan で出すかを判定し、 click で
  // ui.overlays.planOpen を立てる。 PlanApprovalBubble 本体の render + auto-close は ChatPanel が担う。
  const status = useStatus(activeSession)
  const moonlightAvailable = useMoonlightAvailable()

  return (
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
  )
}
