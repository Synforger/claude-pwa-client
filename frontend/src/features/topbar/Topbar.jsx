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
import { useT } from '../../i18n/t.js'
import { useStatus } from '../status-bar/useStatus.js'
import { isApiTab } from '../../_common/apiTab.js'
import { useMoonlightAvailable } from '../screenshare/useMoonlightAvailable.js'
import ExtensionMenu from '../extensions/ExtensionMenu.jsx'
import { subscribe as subscribeTickets, getSnapshot as getTicketsSnapshot } from '../../state/tickets.js'
import { attentionCounts } from '../tickets/ticketGroups.js'
import { useDockedDrawer } from '../session-drawer/useDockedDrawer.js'
import { setDrawerOpen } from '../session-drawer/dockedDrawerOpen.js'

export default function Topbar() {
  const ui = useSyncExternalStore(subscribeUi, getUiSnapshot)
  const sessionsState = useSyncExternalStore(subscribeSessions, getSessionsSnapshot)
  const t = useT()
  // The list stays on the left of a wide screen, so ☰ toggles it there; on any other screen it only opens it, as before
  const docked = useDockedDrawer()
  const { tickets } = useSyncExternalStore(subscribeTickets, getTicketsSnapshot)

  const activeSession = useMemo(
    () => sessionsState.sessions.find(s => s.id === sessionsState.activeId) || null,
    [sessionsState.sessions, sessionsState.activeId],
  )
  const activeSid = activeSession?.id || null
  // An API tab has no Claude Code: no notes, no plan approval (and no terminal to come back from)
  const claudeSid = isApiTab(activeSession) ? null : activeSid
  // 🎫 の数 = このタブ / 全体 (= 操作者が動く票だけ。 全体が 0 なら数は出さない)
  const ticketCounts = useMemo(() => attentionCounts(tickets, activeSid), [tickets, activeSid])
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
      <button className="hamburger" onClick={() => setDrawerOpen(docked ? !ui.overlays.drawer : true, { docked })} aria-label={t('topbar.drawer_toggle')} data-testid="drawer-toggle">
        ☰
      </button>
      <span className="topbar-title">{activeSession?.title || t('topbar.no_session')}</span>
      {/* terminal モード時の chat 復帰ボタン: ⋯メニュー経由が hit test 等で詰まっても
          ここから確実に戻れるよう topbar に独立表示。 chat モード時は出さない。 */}
      {activeViewMode === 'terminal' && activeSid && (
        <button
          className="topbar-icon-btn"
          onClick={() => setActiveViewMode('chat')}
          aria-label={t('topbar.back_to_chat')}
          title={t('topbar.back_to_chat')}
        >
          💬
        </button>
      )}
      {/* topbar 右側のアイコン群。 並びは左→右で ⭐ お気に入り → 🎫 票 → 📋 メモ →
          (📑 plan 承認、 条件付き) → (🔊 声、 声を持つ agent のタブだけ) →
          🖥 モニター → 🧩 拡張。 🎫 は ⭐ の右で、
          票の一覧の入口はここだけなので、 タブが無い時も端末の表示の時も出す。 */}
      {activeViewMode === 'chat' && activeSid && (
        <button
          className="topbar-icon-btn"
          onClick={() => setOverlay('favs', true)}
          aria-label={t('topbar.favorites_label')}
          title={t('topbar.favorites')}
          data-testid="favorites-open-button"
        >
          ⭐
        </button>
      )}
      <button
        className="topbar-icon-btn topbar-tickets-btn"
        onClick={() => setOverlay('tickets', true)}
        aria-label={t('topbar.tickets_label', ticketCounts)}
        title={t('topbar.tickets_label', ticketCounts)}
        data-testid="tickets-open-button"
      >
        🎫
        {ticketCounts.total > 0 && (
          <span className="topbar-tickets-count" data-testid="tickets-count">
            {activeSid ? `${ticketCounts.own}/${ticketCounts.total}` : ticketCounts.total}
          </span>
        )}
      </button>
      {activeViewMode === 'chat' && claudeSid && (
        <button
          className="topbar-icon-btn"
          onClick={() => setOverlay('notes', true)}
          aria-label={t('topbar.notes_label')}
          title={t('topbar.notes')}
          data-testid="notes-open-button"
        >
          📋
        </button>
      )}
      {/* ExitPlanMode 承認待ち: 📋 の隣に常駐する 📑 ボタン。 pending_plan がある時のみ表示、
          脈動ドットで承認待ちを示し、 タップで PlanApprovalBubble (= ChatPanel 内) を開く
          (= ui.overlays.planOpen 経由)。 */}
      {activeViewMode === 'chat' && claudeSid && status?.pending_plan && (
        <button
          className="topbar-icon-btn topbar-plan-btn"
          onClick={() => setOverlay('planOpen', true)}
          aria-label={t('topbar.plan_approval_label')}
          title={t('topbar.plan_approval')}
          data-testid="plan-approval-open-button"
        >
          📑<span className="topbar-plan-dot" />
        </button>
      )}
      {/* Claude Code の承認の窓: 📑 の隣。 pending_permission がある時のみ表示し、 タップで
          PermissionWindowDialog (= ChatPanel 内) を開く (= ui.overlays.permissionOpen 経由)。 */}
      {activeViewMode === 'chat' && claudeSid && status?.pending_permission && (
        <button
          className="topbar-icon-btn topbar-permission-btn"
          onClick={() => setOverlay('permissionOpen', true)}
          aria-label={t('topbar.permission_window_label')}
          title={t('topbar.permission_window')}
          data-testid="permission-window-open-button"
        >
          🔐
        </button>
      )}
      {moonlightAvailable && (
        <button
          className={`screen-toggle ${ui.overlays.desktopOpen ? 'active' : ''}`}
          onClick={() => setOverlay('desktopOpen', !ui.overlays.desktopOpen)}
          aria-label={t('topbar.screenshare_label')}
          title={ui.overlays.desktopOpen ? t('topbar.screenshare_close') : t('topbar.screenshare_open')}
          data-testid="screenshare-toggle"
        >
          🖥
        </button>
      )}
      {/* 拡張の差し口: 🧩 1 個で、 押すと届く拡張の一覧 (= ExtensionMenu)。 右端に置く
          (= ⋯ メニューはステータスバーの右端)。 */}
      <ExtensionMenu />
    </header>
  )
}
